#!/bin/sh
# Only run as root inside the distribution imported by Audilege.
set -eu
export DEBIAN_FRONTEND=noninteractive
if ! dpkg-query -W -f='${db:Status-Status}\n' ca-certificates curl xz-utils libgomp1 libstdc++6 util-linux passwd | awk '$0 != "installed" {bad=1} END {exit bad || NR != 7}'; then
    apt-get -o Acquire::Retries=3 update
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates curl xz-utils libgomp1 libstdc++6 util-linux passwd
fi
if ! id audilege >/dev/null 2>&1; then
    useradd --create-home --shell /bin/sh audilege
fi
