# Run an x86-64 ISO in Termux with QEMU

**Labels:** Termux, Android, QEMU, Virtual Machine, Linux, Command Line, Emulation
**Published:** 2026-09-28
**Target keyword:** run an x86-64 ISO in Termux
**Search description (151 chars):** Run an x86-64 ISO in Termux with QEMU. Fix the wrong package name, the -display none flag and the 5901 port, then see the guest screen in your browser.

Readable copy of `post.html`. `post.html` is the source of truth — never paste this file into Blogger.

---

I wanted to see what a real Linux installer actually does, so I copied an ISO onto my phone to run an x86-64 ISO in Termux. The tutorial's command gave me a black browser tab, an error about SDL, and then a browser that connected to nothing at all. Three separate things were wrong, and not one of them was a QEMU bug.

> If Termux is still new to you, stop here first. Storage permission, the extra-keys row and nano are all covered in [our step-by-step guide to Termux commands, git cloning and nano](https://freestackhub.blogspot.com/2026/09/termux-commands-worth-memorising-basics.html). This post assumes you can move around a shell. What it adds is a program that runs for twenty minutes, wants a gigabyte of RAM, and expects a screen you do not have.

## What QEMU on a phone actually is

Be honest with yourself about what this is before you start. Termux runs inside Android's app sandbox, so QEMU gets no `/dev/kvm`, no VT-x and no Hypervisor.framework. There is no hardware acceleration available at all. Everything runs under TCG, QEMU's just-in-time compiler, which translates each x86 instruction into ARM instructions on the fly. Hardware executes those instructions in a cycle or two; under TCG each one becomes dozens of ARM instructions plus bookkeeping.

Order of magnitude: expect five to twenty times slower than the same guest under KVM on a laptop. A live environment that reaches a login prompt in ninety seconds on a PC can take many minutes here. That is not a bug and no flag fixes it. If your goal is a working Linux on your phone, you already have one, and this is the wrong tool for the job.

The install is bigger than it looks too. The Termux package pulls in 27 dependencies, including `alsa-lib`, `jack2`, `pulseaudio`, `libspice-server` and `libusb`. That is a full audio stack, a remote-display stack and a USB stack that a phone will never use. Budget a few hundred megabytes of download for an emulator you will probably run once.

What it is genuinely good for is reconnaissance. Booting a live ISO costs you 66 MB and a coffee break. Actually installing a distribution, updating it, and keeping it current costs you hours under TCG, and you could have done the same on a free virtual machine. Learn the installer on the phone if you have nothing else. Do not run your infrastructure on it.

## Install qemu, and get the package name right

The package is `qemu-system-x86-64-headless`. Hyphens. Almost every tutorial you will find says `qemu-system-x86_64-headless` with underscores, because that was genuinely the old name. Termux renamed it, so the underscore spelling is now a wrong answer that still reads perfectly well.

```bash
pkg update && pkg upgrade -y
pkg install qemu-system-x86-64-headless qemu-utils -y
qemu-system-x86_64 --version
qemu-img --version
```

Note that the package name and the command disagree, and neither is a typo. Debian-style packages are named with hyphens; the binaries inside them are named with underscores. `qemu-img` arrives in a separate package called `qemu-utils`, which is why that one is on the install line. If you skip it, `qemu-img` simply is not there and the disk section further down cannot run.

The second trap has no fix at all, so check before you spend an evening on it. Termux builds this package for 64-bit phones only and excludes the 32-bit architectures from the build. On an `armv7l` device, `pkg install` can report success while shipping nothing but a manual page, and the next command answers:

> qemu-system-x86_64: command not found

Run `uname -m` first. If it prints `armv7l`, no amount of reinstalling, updating or clearing storage will produce a binary. That is the floor of what this package supports, and the honest answer is to stop, not to keep retrying. `aarch64` is what you need.

## Pick an ISO small enough to be worth it

The Alpine releases directory lists three editions of the same distribution, and the size difference is not a rounding error. For x86_64 at the current stable release: **virtual is 66 MB, standard is 353 MB, extended is 1 GB**. The same page is where you get each edition's `.sha256` file, which you will want in a moment.

Start with **virtual**. It is built to run entirely from RAM, which is the right shape for a guest where every megabyte of memory is being emulated rather than passed through. Save the standard and extended editions for a laptop.

```bash
mkdir -p ~/vms && cd ~/vms
wget https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/alpine-virt-3.24.2-x86_64.iso
wget https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/alpine-virt-3.24.2-x86_64.iso.sha256
sha256sum -c alpine-virt-3.24.2-x86_64.iso.sha256
```

The version number in that filename changes whenever Alpine ships a release. If 3.24.2 is no longer there, open the directory listing and read the current one rather than guessing.

Do not skip the checksum. On a phone, a download interrupted by a call or a dead hotspot leaves a truncated ISO, and a truncated ISO typically boots to a black screen and then a bare `Boot failed` with nothing useful on the terminal. The failure looks identical to "QEMU is broken on Android", which sends you off reinstalling a package that was never the problem. One `sha256sum -c` turns a mystery into a two-second retry.

## Run an x86-64 ISO in Termux without a graphical app

Here is the command, and each flag earns its place. The one that matters most is the last two.

```bash
qemu-system-x86_64 -accel tcg,thread=multi \
  -cdrom alpine-virt-3.24.2-x86_64.iso \
  -drive file=alpine.qcow2,format=qcow2 \
  -m 1024 -smp 2 -display none -vnc 127.0.0.1:1
```

- **`-accel tcg,thread=multi`** — TCG is the only accelerator the sandbox allows, and `thread=multi` lets QEMU run the guest's CPUs on separate ARM cores. On an eight-core phone this is the single biggest speed difference available to you. If your build rejects the property, drop `,thread=multi` and carry on; everything else still works.
- **`-m 1024`** — a gigabyte for the guest. Alpine's virtual edition is comfortable with that. A Debian or Ubuntu desktop ISO wants `2048` at minimum, and on a phone where Android has already claimed half the RAM, asking for more tends to get the whole app killed by the low-memory killer instead.
- **`-smp 2`** — two emulated cores. Going beyond two usually makes things *slower*, because the TCG threads then compete for the same physical cores.
- **`-display none -vnc 127.0.0.1:1`** — the pair that makes this headless.

## Why -nographic is the wrong flag, and why the port is 5901

Most guides tell you to add `-nographic`. For a text-mode guest that is correct advice. For a graphical ISO it is precisely wrong, and it fails quietly rather than loudly. `-nographic` switches off the graphical display *and* redirects the serial port to your terminal, so a distribution that draws its entire installer to the video card has nothing left to draw on. You get the BIOS text, then a boot log, then a login prompt you can type at, while the graphical installer runs somewhere you cannot reach.

What you actually want is `-display none`, which tells QEMU not to open a GUI without touching the serial port, paired with `-vnc 127.0.0.1:1`, which serves the video card's framebuffer over VNC instead. Two different jobs, two different flags.

Leave the display flag out entirely and the build tries to bring up a GUI backend that does not exist on a phone:

> qemu-system-x86_64: could not initialize SDL Could not initialize SDL(2) - exiting

The second thing that catches everyone is the port. A VNC display number is an offset, not the port itself. Display `:0` is TCP 5900, and display `:1` is TCP **5901**. Type `-vnc :1`, then reflexively try to connect to 5900, and the connection is refused by a server that is running perfectly. QEMU tells you the truth in its own output, and that line is the one to read:

> VNC server listening on 127.0.0.1:5901

## Put the console in the browser

A browser cannot speak VNC. VNC is a raw TCP protocol from the 1990s; browsers speak WebSocket and nothing else. Something has to sit in between and translate, and the standard answer is websockify for the bridge plus noVNC for the page. Together they are usually one command.

Termux ships neither of them. I checked the whole package repository, all 2216 package names, and there is no `novnc` and no `websockify`. So this half of the post is a pip step rather than a `pkg install`.

```bash
pkg install python python-numpy
pip install websockify --break-system-packages
git clone --depth 1 https://github.com/novnc/noVNC ~/novnc
```

Installing `python-numpy` before the pip line is not a detail, it is the thing that saves you an evening. websockify depends on numpy. If numpy is not already on the phone, pip decides to build it from source, and on a phone that is a long, hot, completely silent stretch during which the terminal looks exactly like a hung one. Many people kill pip here and conclude that websockify is broken on Android. Installing the Termux package first means pip finds a ready-made build and moves straight on to the thing you wanted.

`--break-system-packages` is Termux's answer to the same wall Debian puts up. Termux's Python is marked as externally managed, and pip refuses to install into it without that flag. Seeing the error, read the message: it is telling you the flag it wants.

Now start QEMU, and then open a **second Termux session** for the bridge. The first one is busy and cannot accept another command until QEMU exits.

```bash
websockify --web ~/novnc 6080 127.0.0.1:5901
```

That one command does both jobs. It serves the noVNC page on port 6080, and it bridges that page's WebSocket to QEMU's raw VNC port. Then open the phone's own browser to:

```
http://127.0.0.1:6080/vnc.html?autoconnect=1
```

That URL works because the page is served from the same host and port that the WebSocket proxy listens on, so noVNC builds a matching address without being told. Serve noVNC any other way and it will construct the WebSocket URL from wherever the page came from, find no bridge there, and leave you with a black rectangle and no error message anywhere. It is the most confusing failure in this entire post, and it is entirely prevented by keeping the page and the proxy on the same port.

A laptop pointed at `127.0.0.1` is talking to the laptop, not to the phone. For a bigger screen, change QEMU to `-vnc 0.0.0.0:1` and open `http://the-phone's-IP:6080/vnc.html?autoconnect=1` from the laptop on the same Wi-Fi. Understand what you are doing first: that is an Alpine live environment with a passwordless root account, reachable by anything else on the network. It is the same decision as [binding a local server to 0.0.0.0](https://freestackhub.blogspot.com/2026/09/how-to-run-a-node-app-in-termux.html) for the same reasons, and the same advice applies. Do it on a network you trust, and put the loopback address back afterwards.

## The ISO is read-only, and everything you do in it disappears

That last flag is an overlay disk, and it is not decoration. `-cdrom` attaches a CD-ROM, which cannot be written. Run the Alpine installer and when it asks where to put the system, the answer cannot be the ISO you booted from. Without a disk to write to, the install either fails or quietly goes nowhere.

```bash
qemu-img create -f qcow2 alpine.qcow2 10G
```

With that image present, the `-drive` flag in the command above gives the guest a blank 10 GB disk to install onto, while the ISO stays pristine and re-bootable. It is the same idea as keeping your work in one folder instead of on the memory stick, applied to a whole machine: one writable layer sitting over an immutable base.

Look at those two numbers again. A 10 GiB virtual size sitting on 196 KiB of real disk is qcow2 being sparse, and it is the reason a modest phone can host something that claims to be a large machine. Now the part that will bite you: **put that file inside `~/vms`, not in `~/storage/downloads`.** Android's emulated shared storage does not reliably honour sparse allocation, so a disk that should cost 196 KB can quietly grow to its full ten gigabytes, and an SD card is worse. It is the same filesystem that refuses the symlinks npm insists on creating, which cost me an evening before I understood it, described in [running a Node app in Termux without the symlink errors](https://freestackhub.blogspot.com/2026/09/how-to-run-a-node-app-in-termux.html). The general rule is simple enough to memorise: anything with real disk or filesystem requirements lives in `~`, and shared storage is only for handing finished files to other apps.

## x86-64 or aarch64: which one you actually need

The same Termux package family ships an aarch64 emulator as a separate subpackage, and it is meaningfully faster, because the instruction set being emulated matches the phone's own. Install it with `pkg install qemu-system-aarch64-headless`.

My opinion, since you will have to choose: **use the aarch64 ISO unless you have a specific reason not to.** An aarch64 Alpine reaches a desktop several times faster, and a beginner's first hour with an emulator goes a great deal better. I would not have written this post differently if the faster path were the easy one.

Here is the catch. An aarch64 guest boots through UEFI rather than BIOS, so it needs an EDK2 firmware file handed over with `-drive if=pflash,...`. Whether Termux's QEMU build ships that firmware is worth checking on your own install before you plan an evening around it. The x86-64 guest boots on SeaBIOS, which QEMU has, and needs no extra file at all. That is precisely why the first run in this post is x86-64.

So the decision comes down to this: **x86-64 emulation is the only way to run a Windows ISO or any x86-only installer**, and that is a completely legitimate reason to accept the slowness. If you just want a working Linux to poke at for an afternoon, aarch64 is the better trade and you should take it.

There is a third option worth knowing about, and it is the fastest of the three. `pkg install qemu-user-x86-64` gives you `qemu-x86_64`, which runs a single x86-64 Linux binary directly, with no BIOS, no kernel and no disk image at all. It is several times faster than a full system because the only thing being emulated is the program itself. It also cannot boot an ISO and is not a substitute for one, but if what you actually needed was to run one x86 tool, this is the command you were looking for and it takes a fraction of the effort.

## When the phone gets hot, slow, or locked

A TCG guest will happily occupy every core you give it, and Android's thermal system will throttle the entire phone in response. Expect warmth, expect the battery indicator to move, and expect your other apps to feel slow while it runs. This is a load, not a bug, and the honest framing is that you are using a laptop-class workload on a phone that was not designed for one.

Lock the screen and the guest stops. You will come back, unlock, and find the page frozen while the terminal still shows the QEMU command as though everything were fine. Nothing crashed. Android stopped scheduling the process, exactly as it does to a background server, and the fix is the same one: a wake lock.

```bash
pkg install termux-api
termux-wake-lock
```

That needs the Termux:API add-on app installed from the same store as Termux itself. Mixing an F-Droid Termux with a Play Store add-on produces a command that is simply `not found`, and no amount of reinstalling inside Termux changes that. When the emulator has done its job, run `termux-wake-unlock`. A wake lock left on next to a full-emulation guest running overnight is how a phone is dead by morning, and that is a decision for the hour you need it rather than a setting to leave armed.

## Errors worth recognising on sight

Match the words, then apply the one fix. Reinstalling everything is how the message that actually mattered scrolls off the screen.

- **E: Unable to locate package qemu-system-x86_64-headless.** You typed underscores. The package is `qemu-system-x86-64-headless`.
- **qemu-system-x86_64: command not found, right after a successful install.** Check `uname -m`. On `armv7l` the package contains no binary and never will.
- **could not initialize SDL(2) - exiting.** You left out the display flag. Add `-display none` and `-vnc 127.0.0.1:1`.
- **Connection refused on 5900.** Display `:1` is port 5901. Read the line QEMU printed when it started.
- **Blank browser page, no error anywhere.** noVNC is being served from a different host or port than the WebSocket bridge. Run websockify with `--web` and open the page from the port websockify itself printed.
- **`qemu-img: command not found`.** You did not install `qemu-utils`.
- **Boot failed, or a black screen after a long download.** Run `sha256sum -c` before you blame QEMU. A truncated ISO looks exactly like this.
- **The install got to about 80% and the phone froze.** The low-memory killer. Lower `-m` to 512 or close other apps. The disk is not the problem.
- **It worked, and then it is gone.** The live session was the ISO. You booted read-only media and never created the `qcow2`.

## Quick recap

1. Install `qemu-system-x86-64-headless` and `qemu-utils`. Hyphens in the package, underscores in the command, and check `uname -m` is `aarch64` before you start.
2. Download the Alpine **virtual** edition, 66 MB, and check it with `sha256sum -c` before pointing QEMU at it.
3. Run with `-accel tcg,thread=multi -display none -vnc 127.0.0.1:1`. Never `-nographic` for a graphical ISO, and read the port off QEMU's own output rather than assuming 5900.
4. Install `python-numpy` before pip-installing websockify, serve noVNC from the same port as the bridge, and open `http://127.0.0.1:6080/vnc.html?autoconnect=1`.
5. Create a `qcow2` inside `~/vms` for anything worth keeping, and take the wake lock only for as long as the guest is running.

Do one thing tonight: boot the 66 MB live environment, look around, and shut it down. Do not install a distribution to it, because that is a job for a free virtual machine where KVM is available, and you will spend the evening waiting instead of learning. The follow-up mistake to avoid is the one I made, which is treating a black screen as a broken emulator when the ISO was simply truncated. Check the checksum first, read the port QEMU printed second, and reinstall nothing until you have read both.

---

## Notes for the next editor

- **Sister posts linked** (all live, using their real `PERMALINK:` URLs):
  - Termux commands / git / nano — `2026/09/termux-commands-worth-memorising-basics.html`
  - Node app in Termux — `2026/09/how-to-run-a-node-app-in-termux.html` (linked twice: the `0.0.0.0` security note and the sparse-file filesystem note)
  - Return link added to the Node post's wake-lock section.
- **Facts verified on 2026-09-28**, do not "correct" them from memory:
  - `qemu-system-x86-64-headless` is the package (hyphens); `qemu-system-x86_64` is the binary (underscores). The underscore package name is the old one and is still what most tutorials print.
  - `qemu-utils` is a real subpackage and is what ships `bin/qemu-img`. Without it, the disk section cannot run.
  - Termux's build sets `TERMUX_PKG_EXCLUDED_ARCHES="arm, i686"`, so a 32-bit phone can install the package and get no binary — hence the `uname -m` check.
  - Termux has no `novnc` and no `websockify` package (all 2216 package names checked), which is why the browser half is a pip step.
  - websockify 0.13.0 depends on `numpy`; `pkg install python-numpy` first, or pip builds numpy from source on the phone.
  - Alpine latest-stable was 3.24.2 (17 Sep 2026): virt 66M, standard 353M, extended 1G, each with a `.sha256` beside it. The version in the URL will change.
  - QEMU's VNC display `:1` is TCP 5901 (5900 + display). `:0` is 5900.
  - The Termux QEMU build passes `--enable-vnc --disable-vnc-sasl --disable-sdl --disable-gtk`, so VNC is compiled in and no GUI backend exists.
- **Possible follow-up post** (not linked here, so no 404): running `qemu-x86_64` user-mode to execute a single x86-64 binary — the same package family ships `qemu-user-x86-64`, and it is several times faster than a full system VM.
