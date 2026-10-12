# Run the actual pinned/patched AppServer against a credential-free Python fake.
# No Official Symphony scheduler, Codex binary or provider process is started.
[source, script, root, scenario, log] = System.argv()
:persistent_term.put(:static_root, root)
:persistent_term.put(:static_command, "/usr/bin/python3 #{script} #{scenario} #{log}")

defmodule SymphonyElixir.Config do
  def local_workspace_root, do: :persistent_term.get(:static_root)
  def codex_runtime_settings(workspace) do
    {:ok, %{approval_policy: "never", thread_sandbox: "workspace-write",
      turn_sandbox_policy: %{"type" => "workspaceWrite", "writableRoots" => [workspace]}}}
  end
  def settings!, do: %{codex: %{command: :persistent_term.get(:static_command),
    read_timeout_ms: 500, turn_timeout_ms: 500}}
end

defmodule SymphonyElixir.PathSafety do
  def canonicalize(path), do: {:ok, Path.expand(path)}
end

defmodule SymphonyElixir.Codex.DynamicTool do
  def bind, do: %{secret_environment_names: [], tool_specs: []}
end

Code.compile_file(source)
workspace = Path.join(root, "workspace")
File.mkdir_p!(workspace)
case SymphonyElixir.Codex.AppServer.start_session(workspace) do
  {:ok, session} ->
    issue = %{id: "static-1", identifier: "STATIC-1", title: "fixture"}
    results = for _ <- 1..3 do
      SymphonyElixir.Codex.AppServer.run_turn(session, "STATIC", issue,
        on_message: fn _ -> :ok end)
    end
    SymphonyElixir.Codex.AppServer.stop_session(session)
    unless Enum.all?(results, &match?({:ok, _}, &1)), do: raise("mock continuation failed")
    IO.puts("STATIC_ACCEPTED_THREE_TURNS")
  {:error, reason} ->
    IO.puts("STATIC_REJECTED:" <> inspect(reason))
end
