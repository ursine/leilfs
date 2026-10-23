# Building Debian packages with debhelper

The native `debian/` packaging is adapted from Debian SaunaFS 5.8.0-1.1. Its
GPL-3.0-or-later notices and changelog history are preserved. See
[README.source](../../debian/README.source) for provenance and adaptations.
CMake builds and stages files; debhelper splits packages, generates runtime
library dependencies and service scripts, handles conffiles, and creates
separate debug packages. CPack remains available for RPMs.

## Build

Build on the Debian or Ubuntu release where the packages will run, in a clean
checkout or disposable builder. Install the build dependencies listed in
`debian/control`. For example, `mk-build-deps` from `devscripts` can generate a
build-dependency package for installation with APT. The build also needs the
normal Debian packaging tools (`build-essential`, `dpkg-dev`, `debhelper`),
the bash-completion debhelper addon (provided by `bash-completion`), and
`asciidoctor`. No network bootstrap of Asciidoctor is performed.

```bash
./packaging/deb/build.sh
```

The wrapper copies the current non-ignored worktree into an isolated source
folder under `_packages/debian`, then runs `dpkg-buildpackage -b -us -uc` there.
Artifacts (`.deb`, `.ddeb`, `.changes` and `.buildinfo`) are written to
`_packages/debian/`. The source/build copy is retained for inspection. Set
`LEILFS_DEB_OUTPUT_DIR` to use another output directory.
The wrapper requires a Git checkout. For an unpacked source archive, run
`dpkg-buildpackage -b -us -uc` directly; artifacts then go into its parent.
Neither compilation nor packaging installs packages or operates host services.

Set `DEB_BUILD_OPTIONS=parallel=N` to control compilation parallelism.
The compiler and installed C++ dependencies must use compatible toolchains.
Set `CC` and `CXX` when selecting a non-default compiler.
Extra arguments to the wrapper go to `dpkg-buildpackage`. `DEB_CMAKE_OPTIONS`
can supply local toolchain paths to CMake. Version and Debian revision are
recorded in `debian/changelog`; development versions use `~dev` so they sort
before the final release. The native architecture and multiarch library path
come from dpkg. Build every role together; disabling components would invalidate
the manifests, and `dh_missing --fail-missing` prevents silent omissions.

## Packages

| DEB | RPM equivalent | Contents |
|---|---|---|
| `leilfs-master` | same | Master and metadata dump/restore tools |
| `leilfs-chunkserver` | same | Storage server |
| `leilfs-metalogger` | same | Metadata backup server |
| `leilfs-client` | same | Mount, client commands and runtime libraries |
| `leilfs-adm` | same | Administration and probe tools |
| `leilfs-cgi` | same | CGI scripts and static assets |
| `leilfs-cgiserv` | same | Standalone HTTP server |
| `leilfs-uraft` | same | HA daemon, helper and HA master unit |
| `leilfs-user` | same | Service account, PAM and limits configuration |
| `leilfs-client-dev` | `leilfs-client-devel` | Development headers |
| `leilfs-client-static` | same | Static C/C++ libraries |

Client-only installation does not pull in server daemons or create a service
account. The web server depends on the CGI assets and service account. HA depends
on the master and admin tools. Runtime client shared libraries are retained,
unlike the RPM spec, because static clients can load the mount helper at runtime.
Legacy executable, header, library and service names remain available.

## Installation and services

Install only the roles needed on each host using APT and their local DEBs.
Supply the corresponding `leilfs-user` DEB when installing a server, and all
required role DEBs when installing HA. Configure hostnames, storage paths,
exports and credentials before enabling a service.

Services retain the `saunafs-*.service` names and are not enabled or started on
initial installation. For example, after configuring the chunkserver:

```bash
sudo systemctl enable --now saunafs-chunkserver.service
```

For multiple labeled chunkserver instances on one host, create one config per
instance, for example `/etc/leil/leil-chunkserver-ssd.cfg` and
`/etc/leil/leil-chunkserver-hdd.cfg`, with separate `DATA_PATH`,
`HDD_CONF_FILENAME`, and `LABEL` values. Start them independently:

```bash
sudo systemctl enable --now saunafs-chunkserver@ssd.service
sudo systemctl enable --now saunafs-chunkserver@hdd.service
```

Each instance has its own PID file under `/run/leil`.

The ordinary and HA master units conflict to prevent simultaneous startup.
HA is opt-in. Upgrades follow Debian's `--no-stop-on-upgrade` policy: running
services stay up during unpacking and may be restarted after configuration.
Review service behavior in a disposable systemd VM before deployment.
Configuration under `/etc/leil` is managed as conffiles. Exports initially allow
no clients; the original example is installed as documentation. The HTTP monitor
binds to localhost, configurable in `/etc/default/saunafs-cgiserv`.
Package scripts never initialize metadata. Service accounts and filesystem data
are retained even on purge; purge removes dpkg-managed configuration.

These renamed packages are not a tested migration path from Debian SaunaFS or
from the earlier experimental monolithic `leilfs` DEB. Inspect/remove conflicting
packages and back up configuration before changing packaging families.

## Validation

```bash
python3 packaging/deb/check.py /path/to/output-directory
lintian /path/to/output-directory/leilfs*.deb
```

The checker inspects all eleven role packages for duplicate ownership, expected
programs, dependencies, configuration, service units and generated scripts.
It does not install packages or operate host services. Test fresh install,
configuration changes, upgrades, removal and purge in a disposable VM before
production deployment. Archive checks and APT simulations do not prove runtime
filesystem or HA interoperability.
