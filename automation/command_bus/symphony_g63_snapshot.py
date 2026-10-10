"""G6.3 stricter close/adoption policy over the unchanged G6.2 snapshot store.

Historical snapshot format/bytes remain immutable. Link targets are preserved
as forensic bytes by the old store, never followed; any link makes G6.3 source
incomplete and keeps its close gate closed. This policy does not call Symphony.
"""
from dataclasses import replace
from .symphony_workspace_snapshot import WorkspaceSnapshotStore


class StrictWorkspaceSnapshotStore(WorkspaceSnapshotStore):
    def load(self, snapshot_id, **binding):
        source = super().load(snapshot_id, **binding)
        if any(e.kind != 'blob' or e.mode not in ('100644', '100755') for e in source.files.values()):
            return replace(source, complete=False)
        return source

    def _result(self, status, reason, snapshot_id):
        result = super()._result(status, reason, snapshot_id)
        source = self.load(snapshot_id)
        links = tuple('rejected_link:' + p for p, e in sorted(source.files.items()) if e.kind != 'blob')
        return replace(result, anomalies=tuple(sorted(set(result.anomalies + links))))
