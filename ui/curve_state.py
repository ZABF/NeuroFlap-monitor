"""Pure state helpers for data-source labels and derived-curve health."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ActiveDataSource:
    kind: str
    display: str
    detail: str = ""

    @classmethod
    def none(cls):
        return cls("none", "None")

    @classmethod
    def replay(cls, path):
        full_path = os.path.abspath(str(path))
        return cls("replay", f"Replay {os.path.basename(full_path)}", full_path)

    @classmethod
    def live(cls, host, port):
        endpoint = f"{str(host).strip()}:{int(port)}"
        return cls("live", f"Live {endpoint}", endpoint)

    @property
    def label(self):
        return f"Source: {self.display}"


@dataclass(frozen=True)
class DerivedCurveHealth:
    missing_refs: tuple = ()
    conflicts: tuple = ()
    cycle: bool = False

    @property
    def valid(self):
        return not self.missing_refs and not self.conflicts and not self.cycle

    @property
    def message(self):
        issues = []
        if self.missing_refs:
            issues.append("Missing: " + ", ".join(self.missing_refs))
        if self.conflicts:
            issues.append("Name conflict: " + ", ".join(self.conflicts))
        if self.cycle:
            issues.append("Dependency cycle")
        return "\n".join(issues)


def expression_refs(node):
    if node is None:
        return set()
    kind = node[0]
    if kind == "ref":
        return {node[1]}
    if kind == "num":
        return set()
    if kind == "unary":
        return expression_refs(node[2])
    if kind == "bin":
        return expression_refs(node[2]) | expression_refs(node[3])
    if kind == "call":
        refs = set()
        for arg in node[2]:
            refs |= expression_refs(arg)
        return refs
    return set()


def resolve_derived_health(curve_specs, available_raw_names):
    """Return health by derived name without requiring data samples or Qt."""
    raw_names = set(available_raw_names)
    derived_specs = {
        name: spec
        for name, spec in curve_specs.items()
        if spec.get("kind") == "expr"
    }
    cache = {}
    visiting = set()

    def resolve(name):
        cached = cache.get(name)
        if cached is not None:
            return cached
        if name in visiting:
            return DerivedCurveHealth(cycle=True)

        visiting.add(name)
        missing = set()
        conflicts = {name} if name in raw_names else set()
        cycle = False
        for ref_name in expression_refs(derived_specs[name].get("ast")):
            if ref_name in derived_specs:
                child = resolve(ref_name)
                missing.update(child.missing_refs)
                conflicts.update(child.conflicts)
                cycle = cycle or child.cycle
            elif ref_name not in raw_names:
                missing.add(ref_name)
        visiting.remove(name)

        health = DerivedCurveHealth(
            missing_refs=tuple(sorted(missing)),
            conflicts=tuple(sorted(conflicts)),
            cycle=cycle,
        )
        cache[name] = health
        return health

    return {name: resolve(name) for name in derived_specs}
