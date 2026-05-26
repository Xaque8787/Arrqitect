"""
ECB Stage 6: Network inference.

Derives the set of platform networks an app participates in,
based on its provides/consumes declarations and the connectivity flag.

Rules:
  Consumer side:
    A consumes entry with connectivity: true AND a matched installed provider
    AND the Docker network already exists causes the consumer to JOIN the
    shared network (scope=external). If the network doesn't exist yet, the
    consumer skips it — the provider update + reconcile cycle will wire it up.

  Provider side:
    When any installed consumer declares connectivity: true against one of this
    app's provided keys, the provider OWNS the network (scope=capability-shared).
    The provider's compose declares the network with driver: bridge.

  No default platform network. Networks are earned, not assumed.
"""

from __future__ import annotations

import json
import subprocess

from app.models.template import TemplateModel
from app.models.ir import NetworkIR, NetworkMembershipIR


def infer_networks(
    template: TemplateModel,
    installed_providers: list[dict],
    installed_consumers: list[dict] | None = None,
) -> tuple[dict[str, NetworkIR], list[NetworkMembershipIR]]:
    """
    Returns:
      networks: dict of network_id -> NetworkIR (all networks this app participates in)
      memberships: list of NetworkMembershipIR for the primary service

    installed_consumers is only passed when compiling a provider app.
    Each entry must have a 'consumes' field (JSON list of consume declarations).
    """
    networks: dict[str, NetworkIR] = {}
    membership_ids: list[str] = []

    # --- Consumer side: join networks for providers this app depends on ---
    for consumed in template.consumes:
        if not consumed.connectivity:
            continue

        provider = _find_provider(consumed.key, installed_providers)
        if provider is None:
            continue

        net_id = _network_id_for_key(consumed.key)

        # Only join if the Docker network already exists — if the provider
        # hasn't created it yet, skip here and let the reconcile after the
        # provider update wire this consumer in.
        if not _docker_network_exists(net_id):
            continue

        networks[net_id] = NetworkIR(
            id=net_id,
            scope="external",
        )
        membership_ids.append(net_id)

    # --- Provider side: own networks when consumers need connectivity ---
    if installed_consumers and template.provides:
        provided_keys = {p.key for p in template.provides}

        for consumer in installed_consumers:
            consumer_consumes = _parse_consumes(consumer.get("consumes", []))
            for c in consumer_consumes:
                if not c.get("connectivity"):
                    continue
                key = c.get("key", "")
                if key not in provided_keys:
                    continue

                net_id = _network_id_for_key(key)
                if net_id not in networks:
                    networks[net_id] = NetworkIR(
                        id=net_id,
                        scope="capability-shared",
                    )
                if net_id not in membership_ids:
                    membership_ids.append(net_id)

    memberships = [
        NetworkMembershipIR(network_id=net_id)
        for net_id in membership_ids
    ]

    return networks, memberships


def _network_id_for_key(capability_key: str) -> str:
    return f"arrqitect_{capability_key.replace('.', '_').replace('-', '_')}"


def _find_provider(capability_key: str, installed_providers: list[dict]) -> dict | None:
    for provider in installed_providers:
        provides = provider.get("provides", [])
        if isinstance(provides, str):
            try:
                provides = json.loads(provides)
            except Exception:
                provides = []
        for p in provides:
            key = p.get("key") if isinstance(p, dict) else str(p)
            if key == capability_key:
                return provider
    return None


def _docker_network_exists(network_name: str) -> bool:
    """Check whether a Docker network exists on the host."""
    try:
        result = subprocess.run(
            ["docker", "network", "inspect", network_name],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _parse_consumes(consumes_raw) -> list[dict]:
    if isinstance(consumes_raw, str):
        try:
            return json.loads(consumes_raw)
        except Exception:
            return []
    return consumes_raw or []
