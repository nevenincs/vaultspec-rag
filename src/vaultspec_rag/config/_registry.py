"""This package's environment variables, declared to the framework registry.

:class:`~vaultspec_rag.config._types.EnvVar` stays the one list of names; this
module is what turns each of those names into a registered framework entry, so
the shared accessors - ``env_value``, ``env_flag``, ``child_environment`` and
``resolve_credential`` - work on them. The entries are built by iterating the
enum rather than restated one by one, because a second list is a list that
drifts: a member added to the enum is registered here the moment it exists.

What an entry declares here is the *name-level* contract, the part the
framework needs in order to answer for a variable: who owns the name, whether
it carries a credential, whether a workspace ``.env`` may supply that
credential, and which framework-scoped name it falls back to. The *value-level*
contract - the admissible range, the coercion, the collective rejection - stays
with the settings schema that already owns it, which is why every entry
declares ``var_type=str`` and no default: nothing is loaded into a framework
configuration field, so the framework never parses one of these values.

The three chained names are the settings this package shares with the rest of
the framework. Each reads its own scoped name first and the shared name behind
it, so one variable configures every package in a session that sets only the
shared one.

**Import cost.** This module reaches ``vaultspec_core.config``, which is an
order of magnitude more expensive to import than the stdlib-only value
vocabulary. Spawn-started workers re-import their whole chain per worker, so a
module on that chain must not import this one; the guards in the test suite
pin the modules that have to stay off it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from vaultspec_core.config import (
    VAULTSPEC_LOG_LEVEL,
    VAULTSPEC_STDIO_WATCHDOG,
    VAULTSPEC_TARGET_DIR,
    ConfigVariable,
    VariableScope,
    register_registry,
)

from ._schema import ENV_OVERRIDE_MAP, SETTING_BOUNDS
from ._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["PACKAGE", "entry"]

#: The distribution these entries belong to. The credential gate resolves this
#: package's install mode - not another's - before it opens a workspace ``.env``.
PACKAGE: Final = "vaultspec-rag"

#: Conventions another tool or standard owns, which this package honours. An
#: explicit list rather than a prefix test: admitting a name to it is the
#: decision that this project does not own the behaviour behind it, and that
#: decision deserves to be reviewed one name at a time. The framework refuses
#: the two halves disagreeing anyway - a product entry must carry the product
#: prefix, and an external one must not - so a misfiling here cannot be built.
_EXTERNAL: Final = frozenset(
    {
        EnvVar.HF_HOME,
        EnvVar.HF_ENDPOINT,
        EnvVar.HF_HUB_OFFLINE,
        EnvVar.HF_HUB_DOWNLOAD_TIMEOUT,
        EnvVar.HF_DEACTIVATE_ASYNC_LOAD,
        EnvVar.HF_HUB_DISABLE_PROGRESS_BARS,
        EnvVar.TRANSFORMERS_OFFLINE,
        EnvVar.TRANSFORMERS_NO_ADVISORY_WARNINGS,
        EnvVar.TRANSFORMERS_VERBOSITY,
        EnvVar.DISABLE_SAFETENSORS_CONVERSION,
        EnvVar.PYTORCH_ENABLE_MPS_FALLBACK,
        EnvVar.UV_CACHE_DIR,
        EnvVar.UV_TOOL_DIR,
        EnvVar.VIRTUAL_ENV,
        EnvVar.TEMP,
        EnvVar.TMP,
        EnvVar.TMPDIR,
    }
)

#: Credentials. A secret's value is withheld from any message that refuses it,
#: and a credential never chains to a second name: a key provisioned for one
#: package must not enrol another.
_SECRETS: Final = frozenset(
    {
        EnvVar.TYPESAFE_API_KEY,
        EnvVar.QDRANT_API_KEY,
    }
)

#: Credentials a workspace-root ``.env`` may supply, and only under the gate:
#: the running interpreter inside the workspace, and this package resolved
#: there as a project dependency. The Qdrant key is deliberately absent - it
#: addresses an operator's own deployment, which repository content has no
#: business naming.
#:
#: No setting belongs here, and the framework refuses to build a non-secret
#: entry marked eligible. That refusal is load-bearing for the download-source
#: settings in particular: where the managed Qdrant binary is fetched from,
#: and which hosts a redirect may reach, must come from the operator's own
#: environment, because a cloned repository that could name them would be
#: choosing the server a host downloads an executable from. For the same
#: reason no entry is declared persistable, which is what would let a
#: workspace's project store supply one.
_WORKSPACE_DOTENV: Final = frozenset(
    {
        EnvVar.TYPESAFE_API_KEY,
    }
)

#: The scoped names that fall back to a framework-scoped one.
_FALLBACKS: Final[Mapping[EnvVar, ConfigVariable]] = {
    EnvVar.RAG_ROOT: VAULTSPEC_TARGET_DIR,
    EnvVar.LOG_LEVEL: VAULTSPEC_LOG_LEVEL,
    EnvVar.STDIO_WATCHDOG: VAULTSPEC_STDIO_WATCHDOG,
}

#: Protective switches: an unusable value leaves the guard in its protective
#: state and warns, rather than refusing the process.
_FAIL_SAFE: Final = frozenset({EnvVar.STDIO_WATCHDOG})

#: Markers this package sets on its own child processes. Documented, but not
#: operator settings, so the collective startup check leaves them alone.
_INTERNAL: Final = frozenset(
    {
        EnvVar.RAG_JUNCTION_PATH,
        EnvVar.RAG_JUNCTION_TARGET,
        EnvVar.PREPROCESS_INVOCATION,
        EnvVar.MONITOR_PYTHON,
    }
)

#: The settings key each override variable feeds, so a description can name it.
_SETTING_KEYS: Final[Mapping[EnvVar, str]] = {
    var: key for key, var in ENV_OVERRIDE_MAP.items()
}

#: What a variable that is not a plain settings override does. A member with
#: neither a settings key nor an entry here fails the totality check below,
#: so a new name cannot land undescribed.
_DESCRIPTIONS: Final[Mapping[EnvVar, str]] = {
    EnvVar.MONITOR_BINARY: (
        "Absolute path to the compiled monitor executable, overriding the "
        "installed vaultspec-rag-monitor command on PATH."
    ),
    EnvVar.MONITOR_PYTHON: (
        "The initialized daemon's absolute Python interpreter, handed to its "
        "monitor child for canonical service commands; not an operator setting."
    ),
    EnvVar.RAG_ROOT: (
        "The workspace root every process kind resolves against. Ranked below "
        "an explicit target named by the invocation and above discovery from "
        "the working directory; blank means unset, and the shared "
        "VAULTSPEC_TARGET_DIR is read behind it."
    ),
    EnvVar.LOG_LEVEL: (
        "The log level every process kind configures its root logger with. "
        "Resolved through the settings wrapper's own log_level property "
        "(delegating to core's resolve_log_level) rather than the generic "
        "settings-override chain, so an unrecognised name is refused instead "
        "of silently reaching an unvalidated settings read; blank means "
        "unset, and the shared VAULTSPEC_LOG_LEVEL is read behind it."
    ),
    EnvVar.MEMORY_PROBE: (
        "Set to a true word to record resident-set and CUDA memory at named "
        "checkpoints through an indexing run. A diagnostic, off by default."
    ),
    EnvVar.TYPESAFE_API_KEY: (
        "TypeSafe API key enabling the hosted classifier. Read from the "
        "process environment first. A workspace-root .env supplies it only "
        "when this package runs from the workspace's own environment in "
        "dependency or dev mode, never for a globally installed tool, and the "
        "resident daemon is handed the resolved value rather than reading any "
        "file of its own."
    ),
    EnvVar.PREPROCESS: (
        "Kill switch for document preprocessing. A false word stops every "
        "root's rules from loading, beating a flag and a configured mode "
        "alike; a true word, unset or blank leaves preprocessing on."
    ),
    EnvVar.STDIO_WATCHDOG: (
        "Lifetime watchdog of the stdio server, on by default. A false word "
        "disarms it, leaving stdin end-of-file as the only exit path. Unset, "
        "blank or an unrecognised word leaves it armed: it is a protective "
        "switch, so a typo warns rather than turning the guard off. The "
        "shared VAULTSPEC_STDIO_WATCHDOG is read behind it."
    ),
    EnvVar.HF_HOME: (
        "Hugging Face cache location, honoured by huggingface_hub. Reported "
        "on status surfaces so an operator can see where models will land."
    ),
    EnvVar.RAG_HF_ENDPOINT: (
        "The model hub every model is downloaded from, as an https URL with "
        "a host and no credentials, query or fragment. Exported to "
        "HF_ENDPOINT when the process starts, where it outranks a value "
        "already there; unset or blank exports nothing and leaves the hub "
        "client's own configuration in force."
    ),
    EnvVar.HF_ENDPOINT: (
        "Hugging Face Hub endpoint, read by huggingface_hub once, when it is "
        "first imported. Overwritten at process start when this package's "
        "own endpoint variable is set, and otherwise left exactly as the "
        "operator set it."
    ),
    EnvVar.HF_HUB_OFFLINE: (
        "Hugging Face Hub offline switch. A true word makes model loads "
        "cache-only; a word the shared vocabulary does not recognise reads as "
        "online, because the owning library, not this package, has authority "
        "over its own value."
    ),
    EnvVar.HF_HUB_DOWNLOAD_TIMEOUT: (
        "The per-read download timeout honoured by huggingface_hub: seconds "
        "with no data before it abandons one attempt. Never set by this "
        "package; named in the remedy a failed model fetch prints."
    ),
    EnvVar.TRANSFORMERS_OFFLINE: (
        "Transformers offline switch, read alongside the Hub's own and under "
        "the same lenient reading."
    ),
    EnvVar.DISABLE_SAFETENSORS_CONVERSION: (
        "Transformers switch suppressing on-the-fly safetensors conversion. "
        "Named here so the literal lives in one place."
    ),
    EnvVar.VIRTUAL_ENV: (
        "The active virtual environment, set by the tool that activated it. "
        "Read to report which environment a command is running from."
    ),
    EnvVar.HF_DEACTIVATE_ASYNC_LOAD: (
        "Transformers switch turning off the parallel weight-materialising "
        "path. Defaulted on Windows, where the parallel path was observed "
        "corrupting weights under concurrent loads; an operator-set value "
        "still wins."
    ),
    EnvVar.HF_HUB_DISABLE_PROGRESS_BARS: (
        "Hugging Face Hub switch suppressing download progress bars. "
        "Defaulted on the search path, whose output is a result envelope."
    ),
    EnvVar.TRANSFORMERS_NO_ADVISORY_WARNINGS: (
        "Transformers switch suppressing advisory warnings. Defaulted on the "
        "search path for the same reason."
    ),
    EnvVar.TRANSFORMERS_VERBOSITY: (
        "Transformers log verbosity. Defaulted to errors only on the search "
        "path so library chatter cannot reach a result envelope."
    ),
    EnvVar.PYTORCH_ENABLE_MPS_FALLBACK: (
        "PyTorch's documented fallback from an unimplemented Metal operator "
        "to the processor. Read with PyTorch's own reading of it - the exact "
        "value 1 - because the behaviour behind it is PyTorch's."
    ),
    EnvVar.UV_CACHE_DIR: (
        "uv's cache location. Read to tell an ephemeral cache environment "
        "apart from an installed tool when explaining a GPU failure."
    ),
    EnvVar.UV_TOOL_DIR: (
        "uv's tool-install location, read for the same classification."
    ),
    EnvVar.TEMP: (
        "The operating system's temporary directory, read to decide whether "
        "an indexed root was throwaway."
    ),
    EnvVar.TMP: "A temporary-directory convention, read alongside TEMP.",
    EnvVar.TMPDIR: "The POSIX temporary-directory convention.",
    EnvVar.RAG_JUNCTION_PATH: (
        "The junction to create, handed to a PowerShell child through its "
        "environment so the path never enters the command string. Set by "
        "this package on its own child; not an operator setting."
    ),
    EnvVar.RAG_JUNCTION_TARGET: (
        "What that junction points at, carried the same way and for the same "
        "reason. Not an operator setting."
    ),
    EnvVar.PREPROCESS_INVOCATION: (
        "The execution envelope handed to a preprocessor child: the source "
        "paths, the mode and the options, as one JSON document. A transport "
        "channel, not an operator setting."
    ),
}


def _scope(var: EnvVar) -> VariableScope:
    """Return who owns *var*'s name."""
    if var in _INTERNAL:
        return VariableScope.INTERNAL
    if var in _EXTERNAL:
        return VariableScope.EXTERNAL
    return VariableScope.PRODUCT


def _description(var: EnvVar) -> str:
    """Return what *var* does, for the operator reading a diagnostic.

    A plain settings override is described from the schema that already
    declares its key and its admissible range, so the two cannot disagree.

    Args:
        var: The variable to describe.

    Returns:
        A one-sentence description.

    Raises:
        KeyError: If *var* is neither a settings override nor described above.
    """
    written = _DESCRIPTIONS.get(var)
    if written is not None:
        return written
    key = _SETTING_KEYS[var]
    bound = SETTING_BOUNDS.get(key)
    if bound is None:
        return f"Overrides the {key} setting."
    return f"Overrides the {key} setting, which must be {bound.shape}."


_undescribed = sorted(
    var.name for var in EnvVar if var not in _DESCRIPTIONS and var not in _SETTING_KEYS
)
if _undescribed:
    raise RuntimeError(
        "environment variables carry no description (add a settings key or a "
        "written one): " + ", ".join(_undescribed)
    )

#: One registered entry per enum member, keyed by the member.
_ENTRIES: Final[Mapping[EnvVar, ConfigVariable]] = {
    var: ConfigVariable(
        env_name=var.value,
        attr_name=None,
        var_type=str,
        default=None,
        description=_description(var),
        secret=var in _SECRETS,
        scope=_scope(var),
        workspace_dotenv=var in _WORKSPACE_DOTENV,
        fail_safe=var in _FAIL_SAFE,
        fallback=_FALLBACKS.get(var),
    )
    for var in EnvVar
}

register_registry(PACKAGE, _ENTRIES.values())


def entry(var: EnvVar) -> ConfigVariable:
    """Return the registered entry for *var*.

    Args:
        var: The variable whose entry is wanted.

    Returns:
        The entry to hand to a framework accessor.
    """
    return _ENTRIES[var]
