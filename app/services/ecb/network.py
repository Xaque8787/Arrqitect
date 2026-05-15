"""
ECB Stage 6: Network inference.

Derives the set of platform networks an app participates in,
based on its provides/consumes declarations and the connectivity flag.

Rules:
  - Every app always joins arrqitect_platform (platform-internal).
  - A consumes entry with connectivity: true causes a capability-shared
    network to be created between the consumer and the matching provider.
  - A consumes entry with connectivity: false has no networking implication
    — it is a registry lookup only.
"""

from __future__ import annotations

from app.models.template import TemplateModel, CapabilityConsumes
from app.models.ir import NetworkIR, NetworkMembershipIR

PLATFORM_NETWORK = "arrqitect_platform"


def infer_networks(
    template: TemplateModel,
    installed_providers: list[dict],
) -> tuple[dict[str, NetworkIR], list[NetworkMembershipIR]]:
    """
    Returns:
      networks: dict of network_id -> NetworkIR (all networks this app participates in)
      memberships: list of NetworkMembershipIR for the primary service
    """
    networks: dict[str, NetworkIR] = {}
    membership_ids: list[str] = []

    # Every app always joins the platform network
    networks[PLATFORM_NETWORK] = NetworkIR(
        id=PLATFORM_NETWORK,
        scope="platform-internal",
    )
    membership_ids.append(PLATFORM_NETWORK)

    # Capability-shared networks for connectivity: true consumes entries
    for consumed in template.consumes:
        if not consumed.connectivity:
            continue

        # Find a matching installed provider
        provider = _find_provider(consumed.key, installed_providers)
        if provider is None:
            continue

        net_id = f"arrqitect_{consumed.key.replace('.', '_').replace('-', '_')}"
        networks[net_id] = NetworkIR(
            id=net_id,
            scope="capability-shared",
        )
        membership_ids.append(net_id)

    memberships = [
        NetworkMembershipIR(network_id=net_id)
        for net_id in membership_ids
    ]

    return networks, memberships


def _find_provider(capability_key: str, installed_providers: list[dict]) -> dict | None:
    for provider in installed_providers:
        provides = provider.get("provides", [])
        if isinstance(provides, str):
            import json
            try:
                provides = json.loads(provides)
            except Exception:
                provides = []
        for p in provides:
            key = p.get("key") if isinstance(p, dict) else str(p)
            if key == capability_key:
                return provider
    return None
