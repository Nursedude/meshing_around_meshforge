# MeshForge: Building a Mesh Network Operations Center with AI at 90 Degrees

*A 3-minute honest assessment of what happens when a retired nurse, a ham radio, and an AI pair-program at the speed of thought*

**By Nursedude (WH6GXZ) & Claude**

---

There's a moment in every engineering project where the velocity of development outpaces your ability to verify what you've built. In traditional software, that moment comes months in. With AI-assisted development, it comes Tuesday afternoon.

MeshForge is three repositories, 4,700+ tests, and roughly 65,000 lines of code built across 14 months. It runs on $35 Raspberry Pis in Hawaii, bridging Meshtastic LoRa mesh radios with zero cloud dependencies. The operator is Shawn Farley — callsign WH6GXZ, retired RN, network engineer, Big Island Radio Club board member — who runs a node called VolcanoAI on the Hawaiian mesh, monitoring tsunami alerts and volcanic activity from his lab.

None of this would exist in its current form without AI pair-programming. And that's both the thesis and the problem.

## The Domain

**meshforge** (v0.5.5-beta, 2,975 tests) — The NOC. Gateway bridge between Meshtastic and Reticulum. TUI built on whiptail dialogs. RF planning tools. Service management. Field-tested on 6+ Pi installations. This is the mature one.

**meshforge-maps** (v0.7.0-beta, 982 tests) — Web visualization. Leaflet.js maps, WebSocket real-time updates, four data collectors with circuit breakers. Architecturally sound. Untested at scale with 100+ nodes.

**meshing_around_meshforge** (v0.6.0, 790 tests) — Rich TUI companion for the meshing-around bot. MQTT monitoring, alert detection, config management. The one we've been debugging all session.

Total: 3,400+ commits. 4,700+ passing tests. One developer. One AI.

## The 90-Degree Turn

Here's what AI-assisted development actually looks like from the inside:

Today's session started with a TCP configuration bug — `port = /dev/ttyACM0` bleeding into TCP configs and crashing the bot. By the end, we'd shipped: a chunk reassembly buffer for weather message truncation, a nano-first config editor replacing a broken TUI table editor, hardware selection expansion with Pi HATs and USB adapters, and a config unification feature so meshforge reads shared settings from the bot's config.ini instead of maintaining duplicate values.

That's 11 commits in one session. Some of them were fixing things we broke in the same session.

This is the 90-degree angle. Traditional development moves forward incrementally — you plan, you build, you test, you ship. AI development moves laterally. You're solving a TCP bug and suddenly you're redesigning the config architecture because the AI traced the root cause three layers deep and found config drift you didn't know you had.

The pace is extraordinary. It's also dangerous.

## What Works

The test counts aren't vanity metrics. When you're shipping 11 commits in a session, 790 passing tests are the guardrails keeping you on the road. Every change runs the full suite before push. Every config edit creates a `.ini.bak`. Every profile application strips stale fields.

The security rules — `MF001` through `MF010` — are linter-enforced across all three repos. No `Path.home()` without SUDO_USER check. No `shell=True` in subprocess. No bare `except:`. These rules exist because AI-generated code will cheerfully introduce every one of these vulnerabilities if you don't have hard guardrails.

The architecture is clean. Gateway logic stays in meshforge. Visualization stays in meshforge-maps. Bot commands stay in meshing_around_meshforge. Boundary rules prevent scope creep.

## What Doesn't

Config management was a disaster for two days straight. Two INI files — `mesh_client.ini` for the client, `config.ini` for the bot — duplicating interface and channel settings. The bot worked fine because it read its own config. The TUI client didn't because it read a different file with stale defaults. I asked Claude three times to fix the config editor before we realized the TUI was reading `config.template` defaults instead of the actual file.

The chunk reassembly buffer went through three iterations: first with a 140-byte threshold (too high — short weather chunks passed through), then buffering ALL messages (created a timer per message, hung the Pi Zero 2W), then settling on 40 bytes. Each fix was logical. Each fix broke something. Each fix was shipped.

Claude sometimes doesn't listen. I'll say "one config, single source of truth" and get back a complex multi-path search with six fallback locations. I'll say "just use nano" and get back a Rich Prompt.ask() editor with template merging. The AI optimizes for completeness when I need simplicity. The questioning and discussion is valuable — Claude caught the config drift issue before I did — but the tendency to over-engineer is real.

## What It's Like

Working with Claude on MeshForge is like pair-programming with someone who has perfect recall, zero institutional knowledge, and unlimited enthusiasm for solving the wrong problem elegantly. The good sessions — and today had stretches of this — feel like thinking at double speed. The bad stretches feel like explaining the same thing to a very smart person who keeps hearing something different.

The AI has changed since I started. Claude on Opus 4.6 with 1M context is substantially more capable than what I started with. It traces code paths across files, understands the domain (Meshtastic, MQTT, LoRa), and generates working implementations that pass tests on the first try more often than not. It also generates implementations that CREATE new bugs with equal confidence. The test suite is the only thing that catches the difference.

I'm a nurse by training. I think in checklists, vital signs, and "first, do no harm." The AI thinks in abstractions, refactors, and "let me add a base class." We meet somewhere in the middle — usually after I've said "that's not what I asked for" at least twice.

## The Numbers

- **3 repos**, 14 months of development
- **4,708 tests** passing across the ecosystem
- **65,000+ lines** of Python, JavaScript, YAML, HTML
- **$35 per node** — Raspberry Pi hardware, zero cloud costs
- **1 developer** with a ham radio license and a second brain that doesn't sleep

## What Comes Next

The config unification shipped today is the right direction — one source of truth, no duplication. The chunk reassembly needs field testing on the Pi2W with real weather data. meshforge-maps needs its first 100-node stress test. The MeshCore 3-way bridge sits in alpha, 2,700 commits diverged, waiting for someone brave enough to test it.

The mesh itself doesn't care about any of this. Packets fly between VolcanoAI and the other nodes on the Hawaiian mesh at 915 MHz, carrying weather alerts and dad jokes in equal measure. The software just tries to keep up.

---

*Shawn Farley (WH6GXZ) is a retired nurse, network engineer, and HAM radio operator on the Big Island of Hawaii. He builds mesh network tools because the volcanoes aren't going to monitor themselves.*

*Claude is an AI assistant by Anthropic that has been pair-programming on MeshForge since its inception. It wrote this piece collaboratively with Shawn, including the parts about not listening. It's working on that.*

*73 de WH6GXZ*

---

*Published from the MeshForge lab, Big Island, Hawaii. All code is open source under GPL-3.0.*
*[github.com/Nursedude](https://github.com/Nursedude)*
