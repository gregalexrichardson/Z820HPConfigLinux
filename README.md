# HPConfigLinux

HPConfigLinux is an experimental Linux utility for inspecting and changing HP BIOS settings. It can edit HP F10 Replicated Setup exports offline and, on the tested HP Z820 workstation, access settings directly through a legacy WMI interface. It provides a command-line interface and an interactive terminal interface.

This is an independent project and is not affiliated with HP. It is not yet a full replacement for HP BIOS Configuration Utility.

> **Experimental firmware writes:** Live reads have been tested on one Z820, and one enumeration change was verified with immediate read-back. Other setting types, BIOS password authentication, bulk restore, and other models have not been validated on hardware. Firmware changes can require physical recovery. Keep a backup and verify changes after reboot.

## Features

- List and edit enumerated settings in F10 Replicated Setup exports without changing firmware.
- Read live settings, filter them, or output JSON.
- Browse settings and make individual changes in a terminal interface.
- Save a live JSON backup, compare it with current settings, and preview and restore selected settings.
- Validate settings before writes and read them back afterwards.

## Requirements

- Linux and Python 3.9 or newer for offline commands.
- For live access: root, debugfs, matching kernel headers and a toolchain compatible with the running kernel. The experimental kernel module must be rebuilt after kernel updates; Secure Boot may reject an unsigned module.
- Live writes are restricted to the HP Z820 Workstation and require the expected legacy WMI interfaces. Live reads have only been tested on that model.

## Quick start

From a checkout, inspect an existing F10 export without root:

```sh
./hpconfig.py list /path/to/CPQSETUP.TXT
./hpconfig.py list /path/to/CPQSETUP.TXT --filter 'Headless Mode'
./hpconfig.py set /path/to/CPQSETUP.TXT 'Headless Mode' Enable -o /path/to/CPQSETUP-new.TXT
```

The `set` command creates a new file and does not change firmware. It preserves the export's encoding, byte-order mark, and line endings. Keep the original export. Applying a full export in F10 may restore other captured settings, so review it, use it on the same machine, and re-export to verify.

To try live access on a Z820, build the module from the checkout and run the utility as root:

```sh
make -C kernel                     # use LLVM=1 if your kernel was built with Clang
sudo ./hpconfig.py live --filter 'Headless Mode'
sudo ./hpconfig.py tui
```

The module is loaded for the operation and unloaded afterwards if the utility loaded it. Live queries may take several seconds. The terminal interface supports arrow keys, `/` to filter, `d` for details, Enter to edit, `r` to refresh, and `q` to quit. Edits require confirmation.

For help with any command, run `./hpconfig.py --help` or `./hpconfig.py COMMAND --help`.

## Live backup and restore

Backups and live output can contain sensitive machine identifiers and settings. Store them privately outside the repository:

```sh
sudo ./hpconfig.py backup /secure/path/z820.json
sudo ./hpconfig.py compare /secure/path/z820.json
sudo ./hpconfig.py restore /secure/path/z820.json 'Num Lock' 'Headless Mode'
```

Backup creates an owner-only file and refuses to overwrite an existing file. Restore checks available machine identity, validates all selected settings, displays a preview, and requires typing `APPLY` in an interactive terminal. It stops at the first failure; a failed write may still have applied. If identity information is unavailable, a match cannot be established, so use backups from the same machine only. `--password` prompts privately for a BIOS setup password, but authentication has not been hardware-validated. Password changes are not supported.

To change one setting directly, use `sudo ./hpconfig.py set-live 'setting name' 'value'`. Some changes require a reboot even when immediate read-back succeeds.

## Install the Python command

From the checkout, run `python3 -m pip install .` to install the `hpconfig` command. For live access, build the kernel module as above and provide its absolute path when using the installed command:

```sh
sudo HPCONFIG_MODULE=/absolute/path/to/kernel/hpconfig_probe.ko hpconfig live
```

Uninstall the Python package with `python3 -m pip uninstall hpconfig-linux`. Remove the checkout and built module separately.

## Development and testing

```sh
python3 -m unittest discover -s tests
```

The optional ACPI simulator test requires `HP_ACPIEXEC`, `HP_DSDT`, and `HP_SSDT` paths in the environment. It checks argument parsing in simulated AML, not real BIOS writes. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance. Do not publish firmware captures, backups, passwords, or machine identifiers.

The Z820 legacy backend queries four WMI setting classes and uses an experimental kernel debugfs interface for the SetBIOSSetting method. The probe exposes a root-only write endpoint and is not read-only. See [HP's BIOS Configuration Utility guide](https://ftp.hp.com/pub/caps-softpaq/cmit/whitepapers/BIOS_Configuration_Utility_User_Guide.pdf) and [Linux tools guide](https://ftp.ext.hp.com/pub/caps-softpaq/cmit/linuxtools/HP_Linux_Tools_Users_Guide.pdf) for background on HP's utilities.

## License

[GNU General Public License v2.0 only](LICENSE).
