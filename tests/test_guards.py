import os
from pathlib import Path

import pytest

from studio.guards import (
    GuardError,
    check_model_allowed,
    is_cloud_model,
    resolve_in_sandbox,
    scan_phi,
)


@pytest.mark.parametrize(
    "name", ["gpt-oss:120b-cloud", "qwen3-coder:480b-cloud", "x:cloud", "A:CLOUD"]
)
def test_cloud_models_rejected(name: str) -> None:
    assert is_cloud_model(name)
    with pytest.raises(GuardError):
        check_model_allowed(name)


@pytest.mark.parametrize("name", ["qwen3:8b", "nomic-embed-text", "llama3.2:3b"])
def test_local_models_allowed(name: str) -> None:
    assert check_model_allowed(name) == name


def test_cloud_allowed_when_block_disabled() -> None:
    assert check_model_allowed("x:cloud", block_cloud=False) == "x:cloud"


def test_sandbox_allows_inside(tmp_path: Path) -> None:
    assert resolve_in_sandbox(tmp_path, "sub/file.txt") == (tmp_path / "sub" / "file.txt").resolve()


@pytest.mark.parametrize("candidate", ["../escape.txt", "a/../../escape", "/etc/passwd"])
def test_sandbox_rejects_traversal(tmp_path: Path, candidate: str) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    with pytest.raises(GuardError):
        resolve_in_sandbox(root, candidate)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_sandbox_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(GuardError):
        resolve_in_sandbox(root, "link/outside.txt")


def test_phi_scan_finds_patterns() -> None:
    text = (
        "Synthetic sample for Acme Health Plan\n"
        "SSN 123-45-6789\n"
        "MRN: AB123456\n"
        "DOB: 01/02/1980\n"
        "Patient: Jane Example, call 555-123-4567\n"
    )
    kinds = {(h.kind, h.line) for h in scan_phi(text)}
    assert {("ssn", 2), ("mrn", 3), ("dob", 4), ("phone_name", 5)} <= kinds
    assert all("6789" not in h.excerpt for h in scan_phi(text))


def test_phi_scan_quiet_on_normal_rfp_text() -> None:
    text = (
        "Acme Health Plan seeks a vendor for FHIR R4 integration.\n"
        "Proposals are due 2026-03-15. Contact the procurement office at 555-010-0000.\n"
        "Section 3.2 requires HIPAA and HITRUST alignment.\n"
    )
    assert scan_phi(text) == []
