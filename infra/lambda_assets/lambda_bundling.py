"""Lambda code bundling for the Python backend.

The application source lives in `<repo>/src` and depends on non-boto packages
(pydantic, PyJWT[crypto]) that are NOT part of the Lambda runtime. We build a
deployment asset that contains both the source tree and those dependencies,
targeting the Lambda **Linux x86_64** platform.

Bundling strategies, in order of preference:

1. **Local, cross-platform pip download** (no Docker required, works on Windows/
   macOS/Linux). We install the runtime requirements with pip's platform
   targeting flags (`--platform manylinux2014_x86_64 --only-binary=:all:`), so
   pip downloads the correct Linux wheels instead of building/using host-native
   binaries. This keeps native deps like `cryptography` valid on Lambda.
2. **Docker bundling** using the official Lambda Python build image, as a
   fallback when local bundling cannot run.

Preferring the local strategy means the common developer path needs neither
Docker nor a Linux host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

import jsii
from aws_cdk import (
    AssetHashType,
    BundlingOptions,
    ILocalBundling,
)
from aws_cdk import aws_lambda as lambda_

# <repo>/src and <repo>/infra/lambda-requirements.txt
_INFRA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_INFRA_DIR)
_SRC_PATH = os.path.join(_REPO_ROOT, "src")
_LAMBDA_REQUIREMENTS = os.path.join(_INFRA_DIR, "lambda-requirements.txt")

# Lambda runtime target for pip platform-specific downloads.
_LAMBDA_PLATFORM = "manylinux2014_x86_64"
_LAMBDA_PYTHON_ABI = "cp312"

# The command Docker runs to assemble the asset (fallback path).
_BUNDLE_CMD = (
    "pip install -r /asset-input/infra/lambda-requirements.txt -t /asset-output && "
    "cp -r /asset-input/src/. /asset-output/"
)


def _copy_source_tree(output_dir: str) -> None:
    """Copy the application source tree into the asset output directory."""
    for entry in os.listdir(_SRC_PATH):
        src = os.path.join(_SRC_PATH, entry)
        dst = os.path.join(output_dir, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


@jsii.implements(ILocalBundling)
class _LocalPipBundling:
    """Bundles the Lambda asset locally by downloading Linux wheels with pip."""

    def try_bundle(self, output_dir: str, *, image: Any = None, **_: Any) -> bool:
        """Bundle into output_dir using cross-platform pip; return success.

        Downloads Linux (manylinux) wheels regardless of the host OS, so the
        asset is valid on the Lambda runtime. Falls back to Docker (returns
        False) only if pip is unavailable or the download fails.

        Args:
            output_dir: Directory CDK expects the asset contents to land in.
            image: The Docker image CDK would otherwise use (unused locally).

        Returns:
            True if local bundling succeeded, False to fall back to Docker.
        """
        if shutil.which("pip") is None and not sys.executable:
            return False
        pip_cmd = [sys.executable, "-m", "pip"]
        try:
            subprocess.run(
                [
                    *pip_cmd,
                    "install",
                    "-r",
                    _LAMBDA_REQUIREMENTS,
                    "-t",
                    output_dir,
                    # Target the Lambda Linux runtime, not the host platform.
                    "--platform",
                    _LAMBDA_PLATFORM,
                    "--python-version",
                    "3.12",
                    "--implementation",
                    "cp",
                    "--abi",
                    _LAMBDA_PYTHON_ABI,
                    "--only-binary=:all:",
                    "--upgrade",
                ],
                check=True,
            )
            _copy_source_tree(output_dir)
            return True
        except (subprocess.CalledProcessError, OSError):
            # Any failure falls back to Docker bundling.
            return False


def build_backend_code(runtime: lambda_.Runtime) -> lambda_.Code:
    """Build the shared Lambda Code asset (source tree + runtime deps).

    Prefers local, cross-platform pip bundling (Linux wheels); falls back to
    Docker with the Lambda build image if local bundling cannot run.

    Args:
        runtime: The Lambda runtime whose bundling image should be used.

    Returns:
        A lambda_.Code asset ready to be shared across all functions.
    """
    return lambda_.Code.from_asset(
        _REPO_ROOT,
        asset_hash_type=AssetHashType.CUSTOM,
        asset_hash="account-management-backend-v3",
        exclude=[
            "**",
            "!src/**",
            "!infra/lambda-requirements.txt",
        ],
        bundling=BundlingOptions(
            image=runtime.bundling_image,
            command=["bash", "-c", _BUNDLE_CMD],
            local=_LocalPipBundling(),
        ),
    )
