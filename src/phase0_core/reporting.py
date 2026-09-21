from __future__ import annotations

from .comparison import ComparisonResult
from .evidence import mask_known_secrets
from .models import ProviderRunResult, ProviderResponse


def render_japanese_summary(
    responses: dict[str, ProviderResponse],
    comparison: ComparisonResult,
    provider_results: dict[str, ProviderRunResult] | None = None,
) -> str:
    lines = [
        "# Phase 0 比較レポート",
        "",
        f"参加Provider数: {comparison.participant_count}",
        f"最多一致数: {comparison.agreement_count}",
        f"結論一致: {comparison.conclusion_match_state.value}",
        f"根拠一致: {comparison.evidence_match_state.value}",
        f"安全ブロック: {'あり' if comparison.safety_block else 'なし'}",
        "正式Council合意: 自動昇格しない",
        "最終判断: 人間",
        "",
        "## Provider別",
    ]
    if provider_results is None:
        for provider, response in sorted(responses.items()):
            lines.append(
                f"- {provider}: answer={response.answer_state.value}, conclusion={response.conclusion_code}, safety={response.safety_warning}"
            )
    else:
        for provider, result in sorted(provider_results.items()):
            conclusion = result.response.conclusion_code if result.response else "UNKNOWN"
            safety = result.response.safety_warning if result.response else "UNKNOWN"
            error = f", error={mask_known_secrets(result.error)}" if result.error else ""
            lines.append(
                f"- {provider}: execution={result.execution_state.value}, participation={result.participation_state.value}, conclusion={conclusion}, safety={safety}{error}"
            )
    return "\n".join(lines) + "\n"
