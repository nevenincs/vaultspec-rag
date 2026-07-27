import pytest

_INSTALL_HELPERS = "vaultspec_rag.tests.integration._install_helpers"
_INDEX_JOB_CONTROL_SUPPORT = (
    "vaultspec_rag.tests.integration._index_job_control_support"
)
_JOBS_REGISTRY_SUPPORT = "vaultspec_rag.tests.integration._jobs_registry_support"
pytest.register_assert_rewrite(
    _INSTALL_HELPERS,
    _INDEX_JOB_CONTROL_SUPPORT,
    _JOBS_REGISTRY_SUPPORT,
)
pytest_plugins = (
    _INSTALL_HELPERS,
    _INDEX_JOB_CONTROL_SUPPORT,
    _JOBS_REGISTRY_SUPPORT,
)
