#!/usr/bin/env python3
"""Check the split Debian archives without installing packages or using services."""
import argparse
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROLES = {'user', 'master', 'chunkserver', 'metalogger', 'client', 'client-dev',
         'client-static', 'adm', 'cgi', 'cgiserv', 'uraft'}
BINARIES = {
    'master': ('usr/sbin/leil-master', 'usr/sbin/leil-metarestore',
               'usr/sbin/leil-metadump', 'usr/sbin/leil-restoremaster'),
    'chunkserver': ('usr/sbin/leil-chunkserver',),
    'metalogger': ('usr/sbin/leil-metalogger',),
    'client': ('usr/bin/leil-mount', 'usr/bin/leil'),
    'adm': ('usr/bin/leil-admin', 'usr/bin/leil-probe'),
    'cgiserv': ('usr/sbin/leil-cgiserver',),
    'uraft': ('usr/sbin/leil-uraft', 'usr/sbin/leil-uraft-helper'),
}
UNITS = {'master': ('saunafs-master',), 'chunkserver': ('saunafs-chunkserver', 'saunafs-chunkserver@'),
         'metalogger': ('saunafs-metalogger',), 'cgiserv': ('saunafs-cgiserv',),
         'uraft': ('saunafs-uraft', 'saunafs-ha-master')}


def field(package, name):
    return subprocess.check_output(['dpkg-deb', '-f', str(package), name], text=True).strip()


def check(directory):
    packages = {}
    for path in directory.glob('leilfs-*.deb'):
        name = field(path, 'Package')
        if name.endswith('-dbgsym'):
            continue
        assert name not in packages, f'Multiple versions of {name}: use a fresh output directory'
        packages[name] = path
    assert set(packages) == {'leilfs-' + role for role in ROLES}, sorted(packages)
    owners, contents, files = {}, {}, {}
    expected_configs = set()
    registered_configs = set()
    versions = {field(path, 'Version') for path in packages.values()}
    assert len(versions) == 1, versions
    with tempfile.TemporaryDirectory(prefix='leilfs-deb-check-') as temporary:
        root = Path(temporary)
        for name, path in packages.items():
            role = name.removeprefix('leilfs-')
            control = root / name
            subprocess.run(['dpkg-deb', '--control', str(path), str(control)], check=True)
            with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(path)], stdout=subprocess.PIPE) as process:
                with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                    for member in archive:
                        location = member.name.removeprefix('./')
                        assert member.uid == 0 and member.gid == 0, (location, member.uid, member.gid)
                        if member.isdir():
                            continue
                        assert location not in owners, (location, name, owners.get(location))
                        assert not location.startswith('usr/local/'), location
                        owners[location] = role
                        if location.startswith('etc/') and member.isfile():
                            expected_configs.add(location)
                        files[location] = member
                        if member.isfile() and (location.endswith('.service') or location.startswith('etc/')):
                            contents[location] = archive.extractfile(member).read().decode()
                assert process.wait() == 0
            conffiles = control / 'conffiles'
            if conffiles.exists():
                for line in conffiles.read_text().splitlines():
                    config = line.split()[0].lstrip('/')
                    assert owners[config] == role, (config, role)
                    registered_configs.add(config)
            for script in ('postinst', 'prerm', 'postrm'):
                script_path = control / script
                if script_path.exists():
                    assert script_path.stat().st_mode & 0o111, script_path
                    subprocess.run(['sh', '-n', str(script_path)], check=True)
            if role == 'user':
                setup = (control / 'postinst').read_text()
                assert 'adduser ' in setup and '--home /var/lib/leil' in setup
                assert 'chown -R' not in setup
                assert 'deluser' not in (control / 'postrm').read_text()
            if role in UNITS:
                assert (control / 'postinst').exists()
                assert (control / 'prerm').exists(), name
                assert 'deb-systemd' in (control / 'postinst').read_text()
                assert 'deb-systemd-invoke stop' in (control / 'prerm').read_text()
        for role, binaries in BINARIES.items():
            for binary in binaries:
                assert owners[binary] == role, binary
                assert files[binary].mode & 0o111, binary
        for role, units in UNITS.items():
            for unit in units:
                paths = [path for path in files if path.endswith('/' + unit + '.service')]
                assert len(paths) == 1 and owners[paths[0]] == role, (unit, paths)
                for line in contents[paths[0]].splitlines():
                    if line.startswith(('ExecStart=', 'ExecStopPost=')):
                        command = line.split('=', 1)[1].split()[0].lstrip('/')
                        assert command in owners, (unit, command)
        assert expected_configs == registered_configs, (expected_configs - registered_configs)
        assert len([path for path in files if path.endswith('.service')]) == 7
        chunk_template = contents[next(path for path in contents
                                       if path.endswith('/saunafs-chunkserver@.service'))]
        assert '-c /etc/leil/leil-chunkserver-%i.cfg' in chunk_template
        assert '-p /run/leil/leil-chunkserver-%i.pid' in chunk_template
        assert owners['usr/share/leil-cgi/leil.cgi'] == 'cgi'
        assert owners['usr/include/leil/leil_c_api.h'] == 'client-dev'
        assert owners['usr/share/bash-completion/completions/leil'] == 'client'
        assert any(path.endswith('/libleil-client.a') and role == 'client-static'
                   for path, role in owners.items())
        assert owners['etc/pam.d/saunafs'] == 'user'
        assert owners['var/lib/leil/metadata.sfs.empty'] == 'master'
        assert not any(line.strip() and not line.startswith('#')
                       for line in contents['etc/leil/leil-exports.cfg'].splitlines())
        assert 'BIND_HOST=127.0.0.1' in contents['etc/default/saunafs-cgiserv']
        assert 'saunafs-ha-master.service' in next(text for path, text in contents.items()
                                                  if path.endswith('/saunafs-master.service'))
        for role in ('master', 'metalogger', 'chunkserver', 'cgiserv'):
            assert 'leilfs-user' in field(packages['leilfs-' + role], 'Depends'), role
        for role in ('client', 'adm', 'cgi'):
            deps = field(packages['leilfs-' + role], 'Depends')
            assert 'leilfs-user' not in deps and 'leilfs-master' not in deps, (role, deps)
        for role in ('client', 'master', 'chunkserver', 'metalogger', 'adm', 'uraft'):
            assert 'libc6' in field(packages['leilfs-' + role], 'Depends'), role
        assert any(path.endswith('/libleilmount_shared.so') and role == 'client'
                   for path, role in owners.items())
        assert 'leilfs-cgi ' in field(packages['leilfs-cgiserv'], 'Depends')
        assert 'leilfs-master ' in field(packages['leilfs-uraft'], 'Depends')
        assert 'leilfs-adm ' in field(packages['leilfs-uraft'], 'Depends')
        for role in ('user', 'cgi', 'cgiserv'):
            assert field(packages['leilfs-' + role], 'Architecture') == 'all'
    print('All 11 role DEBs passed ownership, dependency, conffile, service and script checks.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Directory containing one complete set of role DEBs')
    check(parser.parse_args().directory)
