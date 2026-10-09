# Run with mix test --no-start and G51_BASELINE_DIR pointing to git-show pin sources.
# Dummy OTP tasks only; no application/scheduler/AppServer/provider is started.
defmodule SymphonyG51LifecycleTest do
  use ExUnit.Case, async: false
  alias SymphonyElixir.{AgentRunner, G5Observer, Orchestrator, Workflow}
  alias SymphonyElixir.Tracker.Issue

  setup_all do
    baseline = System.fetch_env!("G51_BASELINE_DIR")
    source = File.read!(Path.join(baseline, "orchestrator.ex"))
    Code.compile_string(String.replace(source, "SymphonyElixir.Orchestrator", "SymphonyG51Baseline"))
    Application.ensure_all_started(:yaml_elixir)
    :ok
  end

  setup do
    root = Path.join(System.tmp_dir!(), "g51-fixture-#{System.unique_integer([:positive])}")
    File.mkdir_p!(root)
    events = Path.join(root, "events.jsonl")
    File.write!(events, "")
    workflow = Path.join(root, "WORKFLOW.md")
    SymphonyElixir.TestSupport.write_workflow_file!(workflow,
      tracker_kind: "memory", workspace_root: Path.join(root, "workspaces"),
      codex_command: "G51_STATIC_PROVIDER_FORBIDDEN", observability_enabled: false)
    Workflow.set_workflow_file_path(workflow)
    # Public STATIC fixture key, not a production credential.
    old = for name <- ["SYMPHONY_G5_OBSERVER_EVENTS", "SYMPHONY_G5_OBSERVER_KEY_HEX"], into: %{},
      do: {name, System.get_env(name)}
    System.put_env("SYMPHONY_G5_OBSERVER_EVENTS", events)
    System.put_env("SYMPHONY_G5_OBSERVER_KEY_HEX", Base.encode16(String.duplicate("f", 32)))
    on_exit(fn ->
      Enum.each(old, fn {key, value} -> SymphonyElixir.TestSupport.restore_env(key, value) end)
      Workflow.clear_workflow_file_path()
      # Leave fixture output for independent Python verification; no Git cleanup.
    end)
    {:ok, root: root, events: events}
  end

  defp dummy_turns(count) do
    receive do
      {:simulated_turn, recipient} ->
        send(recipient, {:simulated_turn_completed, count + 1})
        dummy_turns(count + 1)
      :return -> :ok
    end
  end

  defp worker(root, module \\ Orchestrator, observe \\ true) do
    sup = start_supervised!(Task.Supervisor, id: make_ref())
    {:ok, pid} = Task.Supervisor.start_child(sup, fn -> dummy_turns(0) end)
    ref = Process.monitor(pid)
    issue = %Issue{id: "g51-static", identifier: "GH-STATIC", state: "In Progress", dispatchable: true, url: "https://fixture.invalid"}
    workspace = Path.join([root, "workspaces", issue.identifier])
    File.mkdir_p!(workspace)
    observation = if observe, do: G5Observer.start()
    entry = %{pid: pid, ref: ref, identifier: issue.identifier, issue: issue,
      worker_host: nil, workspace_path: workspace, session_id: nil, last_codex_event: nil,
      last_codex_timestamp: nil, last_codex_message: nil, started_at: nil,
      retry_attempt: 1, turn_count: 0, g5_observer: observation}
    state = struct(Module.concat(module, State), running: %{issue.id => entry},
      claimed: MapSet.new([issue.id]), task_supervisor: sup, max_concurrent_agents: 1,
      codex_totals: %{input_tokens: 0, output_tokens: 0, total_tokens: 0, seconds_running: 0})
    runtime = %{worker_host: nil, workspace_path: workspace,
      g5_worker_run_id: observation && observation.worker_run_id}
    {:noreply, state} = module.handle_info({:worker_runtime_info, issue.id, runtime}, state)
    {issue, state, pid, ref}
  end

  defp lines(path), do: path |> File.read!() |> String.split("\n", trim: true)
  defp wait_lines(path, count, attempts \\ 100)
  defp wait_lines(path, count, attempts) when attempts > 0 do
    if length(lines(path)) == count do
      lines(path)
    else
      Process.sleep(10)
      wait_lines(path, count, attempts - 1)
    end
  end
  defp wait_lines(path, count, 0), do: flunk("expected #{count} signed lines: #{inspect(lines(path))}")
  defp payload(line), do: line |> Jason.decode!() |> Map.fetch!("payload_json") |> Jason.decode!()

  defp finish(module, state, pid, ref, reason \\ :normal) do
    if reason == :normal, do: send(pid, :return), else: Process.exit(pid, reason)
    assert_receive {:DOWN, ^ref, :process, ^pid, ^reason}, 1000
    {:noreply, result} = module.handle_info({:DOWN, ref, :process, pid, reason}, state)
    result
  end

  defp normalized(state) do
    state |> Map.from_struct() |> Map.update!(:running, fn running ->
      Map.new(running, fn {key, entry} -> {key, Map.drop(entry, [:pid, :ref, :g5_observer])} end)
    end) |> Map.drop([:task_supervisor]) |> Map.update!(:retry_attempts, fn retries ->
      Map.new(retries, fn {key, entry} ->
        # Assert the real scheduled delay separately; only nondeterministic refs/time are omitted.
        {key, Map.drop(entry, [:timer_ref, :retry_token, :due_at_ms])}
      end)
    end)
  end

  defp cancel_timers(state) do
    Enum.each(state.retry_attempts, fn {_id, entry} -> Process.cancel_timer(entry.timer_ref) end)
  end

  test "case 1: two natural continuation decisions then tracker close stops a real OTP task and records STOPPED", ctx do
    {issue, state, pid, ref} = worker(ctx.root)
    for turn <- 1..2 do
      send(pid, {:simulated_turn, self()})
      assert_receive {:simulated_turn_completed, ^turn}
      assert {:continue, ^issue} = AgentRunner.continue_with_issue_for_test(issue, fn _ -> {:ok, [issue]} end)
    end
    closed = %{issue | state: "Closed"}
    result = Orchestrator.reconcile_issue_states_for_test([closed], state)
    assert result.running == %{}
    refute Process.alive?(pid)
    refute_receive {:DOWN, ^ref, :process, ^pid, _}, 20
    refute File.exists?(state.running[issue.id].workspace_path)
    [start, stop] = wait_lines(ctx.events, 2) |> Enum.map(&payload/1)
    assert start["kind"] == "STARTED"
    assert stop["kind"] == "TERMINAL"
    assert stop["status"] == "WORKER_STOPPED"
    assert start["worker_run_id"] == stop["worker_run_id"]
    assert start["workspace"] == stop["workspace"]
    if output = System.get_env("G51_SIGNED_FIXTURE_OUTPUT"), do: File.cp!(ctx.events, output)
  end

  test "case 2/4: real natural DOWN is sole terminal authority; repeated notification is a no-op", ctx do
    {issue, state, pid, ref} = worker(ctx.root)
    result = finish(Orchestrator, state, pid, ref)
    {:noreply, duplicate} = Orchestrator.handle_info({:DOWN, ref, :process, pid, :normal}, result)
    assert duplicate == result
    G5Observer.terminal(state.running[issue.id], "WORKER_COMPLETED")
    [_, terminal] = wait_lines(ctx.events, 2) |> Enum.map(&payload/1)
    assert terminal["status"] == "WORKER_COMPLETED"
    Process.sleep(20)
    assert length(lines(ctx.events)) == 2
    assert result.retry_attempts[issue.id].attempt == 1
    assert Process.read_timer(result.retry_attempts[issue.id].timer_ref) in 800..1000
    cancel_timers(result)
  end

  test "failure DOWN remains FAILED and upstream exponential retry is unchanged", ctx do
    {issue, state, pid, ref} = worker(ctx.root)
    result = finish(Orchestrator, state, pid, ref, :fixture_failure)
    [_, terminal] = wait_lines(ctx.events, 2) |> Enum.map(&payload/1)
    assert terminal["status"] == "WORKER_FAILED"
    assert result.retry_attempts[issue.id].attempt == 2
    assert Process.read_timer(result.retry_attempts[issue.id].timer_ref) in 19_800..20_000
    cancel_timers(result)
  end

  test "case 5: stale runtime identity never rebinds an observed lifetime", ctx do
    {issue, state, pid, ref} = worker(ctx.root)
    entry = state.running[issue.id]
    runtime = %{g5_worker_run_id: String.duplicate("0", 32), workspace_path: "/wrong-workspace"}
    {:noreply, updated} = Orchestrator.handle_info({:worker_runtime_info, issue.id, runtime}, state)
    assert updated.running[issue.id].g5_observer == entry.g5_observer
    # Observation protection does not gate upstream's runtime-info behavior.
    assert updated.running[issue.id].workspace_path == "/wrong-workspace"
    result = finish(Orchestrator, updated, pid, ref)
    [start, stop] = wait_lines(ctx.events, 2) |> Enum.map(&payload/1)
    assert start["workspace"] == stop["workspace"]
    assert stop["workspace"] == entry.workspace_path
    cancel_timers(result)
  end

  test "case 6: unavailable, nonregular and stalled writer never delay or change worker termination", ctx do
    for target <- [Path.join(ctx.root, "missing"), ctx.root] do
      System.put_env("SYMPHONY_G5_OBSERVER_EVENTS", target)
      {issue, state, pid, _ref} = worker(ctx.root)
      # Also suspend the writer: observation delivery must remain asynchronous.
      writer = state.running[issue.id].g5_observer.writer
      :erlang.suspend_process(writer)
      {micros, result} = :timer.tc(fn -> Orchestrator.reconcile_issue_states_for_test([%{issue | state: "Closed"}], state) end)
      assert micros < 500_000
      assert result.running == %{}
      refute Process.alive?(pid)
      :erlang.resume_process(writer)
      monitor = Process.monitor(writer)
      assert_receive {:DOWN, ^monitor, :process, ^writer, :normal}, 1000
    end
    assert lines(ctx.events) == []
  end

  test "case 7: patched/baseline OTP callbacks agree on completion, failure, reconciliation and capacity", ctx do
    for scenario <- [:normal, :failure, :closed, :nonactive, :active] do
      results = for module <- [SymphonyG51Baseline, Orchestrator] do
        {issue, state, pid, ref} = worker(ctx.root, module, module == Orchestrator)
        result = case scenario do
          :normal -> finish(module, state, pid, ref)
          :failure -> finish(module, state, pid, ref, :fixture_failure)
          :closed -> module.reconcile_issue_states_for_test([%{issue | state: "Closed"}], state)
          :nonactive -> module.reconcile_issue_states_for_test([%{issue | state: "Backlog"}], state)
          :active ->
            active = module.reconcile_issue_states_for_test([issue], state)
            assert module.should_dispatch_issue_for_test(%{issue | id: "other"}, active) == false
            final = finish(module, active, pid, ref)
            final
        end
        if scenario in [:normal, :failure, :active] do
          delay = Process.read_timer(result.retry_attempts[issue.id].timer_ref)
          assert delay in (if scenario == :failure, do: 19_800..20_000, else: 800..1000)
        end
        cancel_timers(result)
        normalized(result)
      end
      assert Enum.at(results, 0) == Enum.at(results, 1), "scheduler difference in #{scenario}"
    end
  end

  test "case 7: all functions outside the explicit observation seams match the pin AST" do
    baseline = System.fetch_env!("G51_BASELINE_DIR")
    for {file, allowed} <- [
      {"orchestrator.ex", [:handle_info, :terminate_running_issue, :stop_and_block_issue, :spawn_issue_on_worker_host]},
      {"agent_runner.ex", [:run_on_worker_host, :send_worker_runtime_info]}
    ] do
      functions = fn source ->
        ast = Code.string_to_quoted!(source)
        {_ast, defs} = Macro.prewalk(ast, [], fn
          {kind, _, [head | _]} = node, acc when kind in [:def, :defp] ->
            call = case head do {:when, _, [call | _]} -> call; call -> call end
            {name, _, _} = call
            clean = Macro.prewalk(node, fn
              {form, meta, args} when is_list(meta) -> {form, [], args}
              node -> node
            end)
            observation_seam = if name == :handle_info do
              signature = Macro.to_string(head)
              String.contains?(signature, ":DOWN") or String.contains?(signature, ":worker_runtime_info")
            else
              name in allowed
            end
            {node, if(observation_seam, do: acc, else: [clean | acc])}
          node, acc -> {node, acc}
        end)
        defs
      end
      assert functions.(File.read!(Path.join(baseline, file))) == functions.(File.read!("lib/symphony_elixir/#{file}"))
    end
  end

  test "disabled or dead observer does not require worker gates", ctx do
    System.delete_env("SYMPHONY_G5_OBSERVER_KEY_HEX")
    assert G5Observer.start() == nil
    {_, state, pid, ref} = worker(ctx.root)
    result = finish(Orchestrator, state, pid, ref)
    assert lines(ctx.events) == []
    cancel_timers(result)
  end
end
