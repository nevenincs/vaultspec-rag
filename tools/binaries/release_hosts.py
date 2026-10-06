"""The hosts a GitHub release download may be redirected to."""

from __future__ import annotations

from typing import Final

#: GitHub answers a release-asset request with a redirect to its object
#: store: ``release-assets.githubusercontent.com`` today,
#: ``objects.githubusercontent.com`` before the asset host moved. The build
#: tools state this set themselves, so nothing an operator configures for the
#: service's own downloads decides where a build toolchain is fetched from.
GITHUB_RELEASE_REDIRECT_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
