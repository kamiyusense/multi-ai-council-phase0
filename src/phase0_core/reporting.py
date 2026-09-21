from __future__ import annotations

from .comparison import ComparisonResult
from .models import ProviderResponse


def render_japanese_summary(
    responses: dict[str, ProviderResponse],
    comparison: ComparisonResult,
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
    for provider, response in sorted(responses.items()):
        lines.extend(
            [
                f"- {provider}: answer={response.answer_state.value}, conclusion={response.conclusion_code}, safety={response.safety_warning}",
            ]
        )
    return "\n".join(lines) + "\n"
