#!/usr/bin/env python3
"""Simple accelerating single-LED rings and button wave for TX16S MK3.

Install once on Windows:
    py -m pip install hidapi

Run with the custom individual-LED firmware in USB Joystick/Gamepad mode:
    py tools/tx16smk3_led_frame_test.py

Each ring has exactly one lit LED, and exactly one button LED is lit. The rings
rotate in opposite directions; the button LED moves B1..B6..B1. The pattern
accelerates until its stable update limit; Ctrl+C stops it.
"""

from __future__ import annotations

import sys
import time
from typing import Any


VID = 0x1209
PID = 0x4F54
PROTOCOL_VERSION = 1
COMMAND_SET_COLOR = 1
COMMAND_RELEASE = 2
COMMAND_KEEPALIVE = 3
COMMAND_SET_FRAME = 4
TARGET_INDIVIDUAL_LED = 1
TARGET_GIMBAL_RINGS = 0
TARGET_ALL = 2
REPORT_ID = 0
FRAME_REPORT_SIZE = 80  # version + command + 26 RGB triples

REPORT_GAP_SECONDS = 0.0
INITIAL_STEP_SECONDS = 0.55
ACCELERATION_FACTOR = 0.92
# One full frame replaces the previous pending frame in firmware, so a slow
# main loop skips obsolete frames instead of displaying a delayed backlog.
MIN_STEP_SECONDS = 0.02
BLACKOUT_RETRIES = 3
BLACKOUT_SETTLE_SECONDS = 0.35

BUTTONS = [0, 1, 2, 3, 4, 5]  # B1..B6
LEFT_RING = [19, 18, 17, 16, 25, 24, 23, 22, 21, 20]  # L0..L9, clockwise
RIGHT_RING = [9, 10, 11, 12, 13, 14, 15, 6, 7, 8]  # R0..R9, clockwise

BLACK = (0, 0, 0)
BUTTON_COLOR = (0, 100, 255)  # blue
LEFT_COLOR = (0, 180, 255)  # cyan-blue
RIGHT_COLOR = (255, 60, 0)  # orange-red


def packet(command: int, target: int, rgb=(0, 0, 0), led_index: int = 0) -> list[int]:
    red, green, blue = rgb
    return [PROTOCOL_VERSION, command, target, red, green, blue, led_index, 0]


def frame_packet(colors: dict[int, tuple[int, int, int]]) -> list[int]:
    """Encode RGB values for physical LED indices 0..25 in one report."""
    payload = [PROTOCOL_VERSION, COMMAND_SET_FRAME]
    for led_index in range(26):
        payload.extend(colors.get(led_index, BLACK))
    assert len(payload) == FRAME_REPORT_SIZE
    return payload


def send_report(device: Any, payload: list[int]) -> None:
    # The unnumbered feature report is 80 bytes; pad legacy commands for hosts
    # that require the exact descriptor-reported feature length.
    if len(payload) > FRAME_REPORT_SIZE:
        raise ValueError("HID report je dlhší než 80 bajtov")
    padded = payload + [0] * (FRAME_REPORT_SIZE - len(payload))
    sent = device.send_feature_report([REPORT_ID, *padded])
    if sent is not None and sent <= 0:
        raise OSError("hidapi neodoslal HID Feature report")


def choose_device(hid: Any) -> dict[str, Any]:
    devices = [d for d in hid.enumerate() if d.get("vendor_id") == VID and d.get("product_id") == PID]
    if not devices:
        raise RuntimeError("Rádio 1209:4F54 sa nenašlo. Skontroluj USB a režim Joystick/Gamepad.")
    print("Nájdené HID rozhrania TX16S MK3:")
    for i, d in enumerate(devices):
        print(f"  {i}: {d.get('product_string') or '(bez názvu)'} "
              f"usage={d.get('usage_page', 0):04X}:{d.get('usage', 0):04X} "
              f"interface={d.get('interface_number', '?')}")
    if len(devices) == 1:
        return devices[0]
    while True:
        try:
            i = int(input("Vyber číslo HID rozhrania rádia: ").strip())
            if 0 <= i < len(devices):
                return devices[i]
        except ValueError:
            pass
        print("Zadaj platné číslo zo zoznamu.")


class Link:
    def __init__(self, device: Any):
        self.device = device

    def send(self, payload: list[int]) -> None:
        send_report(self.device, payload)
        if REPORT_GAP_SECONDS:
            time.sleep(REPORT_GAP_SECONDS)


def blackout(link: Link) -> None:
    # Release previous state, then black all 26 physical LEDs in one frame.
    link.send(packet(COMMAND_RELEASE, TARGET_ALL))
    link.send(frame_packet({led: BLACK for led in range(26)}))
    time.sleep(BLACKOUT_SETTLE_SECONDS)


def confirm_blackout(link: Link) -> bool | None:
    for attempt in range(1, BLACKOUT_RETRIES + 1):
        blackout(link)
        print(f"Všetky LED dostali RGB(0,0,0), pokus {attempt}/{BLACKOUT_RETRIES}.")
        while True:
            answer = input("Sú všetky LED zhasnuté? [a/n, q = skončiť]: ").strip().lower()
            if answer in {"a", "y", "ano", "yes"}:
                return True
            if answer in {"q", "quit", "stop"}:
                return None
            if answer in {"n", "nie", "no"}:
                break
            print("Zadaj a = áno, n = nie, q = skončiť.")
    return False


def effect_step(step: int) -> dict[int, tuple[int, int, int]]:
    """One lit LED on each ring and one lit button LED."""
    colors = {led: BLACK for led in BUTTONS + LEFT_RING + RIGHT_RING}

    for ring, head, base_color in (
        (LEFT_RING, step % len(LEFT_RING), LEFT_COLOR),
        (RIGHT_RING, (-step) % len(RIGHT_RING), RIGHT_COLOR),
    ):
        colors[ring[head]] = base_color

    # Reflect at each end: B1, B2, ... B6, B5, ... B2, then repeat.
    span = len(BUTTONS) - 1
    position = step % (2 * span)
    if position > span:
        position = 2 * span - position
    colors[BUTTONS[position]] = BUTTON_COLOR
    return colors


def main() -> int:
    try:
        import hid
    except ImportError:
        print("Chýba hidapi. Nainštaluj: py -m pip install hidapi", file=sys.stderr)
        return 2

    device = None
    link = None
    try:
        info = choose_device(hid)
        device = hid.device()
        device.open_path(info["path"])

        print("\nRingy: na každom svieti iba jedna LED.")
        print("Ľavý ring sa točí v smere hodinových ručičiek, pravý opačne.")
        print("Tlačidlá: svieti iba jedna LED, pohyb B1 → B6 → B1.")
        print("Naraz svietia presne tri LED. Každý krok posiela stav všetkých 26 LED v jednom HID reporte.")
        print("Efekt zrýchľuje až po limit 20 ms na snímku (50 snímok/s); rádio môže preskočiť zastarané snímky bez fronty. Zastavíš ho Ctrl+C.")
        input("Stlač Enter na prípravu LED... ")

        link = Link(device)
        print("Zhasínam LED a kontrolujem počiatočný stav...")
        dark = confirm_blackout(link)
        if dark is None:
            return 0
        if not dark:
            print("LED sa nepodarilo potvrdene zhasnúť; animáciu nespúšťam.")
            return 1

        step = 0
        interval = INITIAL_STEP_SECONDS
        print("Animácia beží. Ukonči ju cez Ctrl+C.")

        while True:
            started = time.monotonic()
            current = effect_step(step)
            link.send(frame_packet(current))

            work_seconds = time.monotonic() - started
            print(f"\rSnímka {step + 1} | interval {interval * 1000:.0f} ms "
                  f"| HID zápis {work_seconds * 1000:.0f} ms", end="", flush=True)
            remaining = interval - work_seconds
            if remaining > 0:
                time.sleep(remaining)

            step += 1
            interval = max(MIN_STEP_SECONDS, interval * ACCELERATION_FACTOR)
    except KeyboardInterrupt:
        print("\nAnimácia zastavená.")
        return 130
    except Exception as exc:
        print(f"\nChyba: {exc}", file=sys.stderr)
        return 1
    finally:
        if device is not None:
            try:
                send_report(device, packet(COMMAND_RELEASE, TARGET_ALL))
                print("LED override uvoľnený; EdgeTX preberá riadenie LED.")
            except Exception as exc:
                print(f"Upozornenie: nepodarilo sa uvoľniť LED: {exc}", file=sys.stderr)
            try:
                device.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
