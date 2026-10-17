"""正式身份断言的确定性解析；运行时、读侧与章末核对共用"""

from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityResolution:
    representatives: dict[str, str]
    conflicts: dict[str, str]


def resolve_identities(
    identifiers: set[str],
    same: set[tuple[str, str]],
    different: set[tuple[str, str]],
    preferred: set[str],
) -> IdentityResolution:
    """只有正式同一断言建分量；冲突分量原样保留，唯一标记优先，否则按稳定 id 选代表"""
    parent = {identifier: identifier for identifier in identifiers}

    def find(identifier: str) -> str:
        while parent[identifier] != identifier:
            parent[identifier] = parent[parent[identifier]]
            identifier = parent[identifier]
        return identifier

    for left, right in sorted(same):
        if left in parent and right in parent:
            parent[find(right)] = find(left)
    groups: dict[str, set[str]] = {}
    for identifier in sorted(identifiers):
        groups.setdefault(find(identifier), set()).add(identifier)
    blocked = {
        find(left) for left, right in different if left in parent and right in parent and find(left) == find(right)
    }
    representatives, conflicts = {}, {}
    for root, members in groups.items():
        marked = members & preferred
        reason = (
            "identity_assertion_conflict"
            if root in blocked
            else "representative_ambiguous"
            if len(marked) > 1
            else None
        )
        if reason:
            conflicts.update(dict.fromkeys(members, reason))
            representatives.update({member: member for member in members})
        else:
            representative = min(marked or members)
            representatives.update(dict.fromkeys(members, representative))
    return IdentityResolution(representatives, conflicts)
