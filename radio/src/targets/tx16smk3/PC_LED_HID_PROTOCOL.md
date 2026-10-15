# TX16S MK3 PC LED HID protocol

The PC feedback interface is an unnumbered HID Feature report with an
8-byte firmware payload. HIDAPI prepends report ID `0` on the host, so its
write buffer has 9 bytes total.

| Byte | Meaning |
| --- | --- |
| 0 | Protocol version (`1`) |
| 1 | Command |
| 2 | Target |
| 3 | Red (`0..255`) |
| 4 | Green (`0..255`) |
| 5 | Blue (`0..255`) |
| 6 | Physical LED index for the individual LED target (`0..25`) |
| 7 | Reserved; send `0` |

Commands:

| Value | Name | Effect |
| --- | --- | --- |
| 1 | Set color | Sets a uniform ring override or one physical LED override, based on target. |
| 2 | Release | Releases the selected ring, individual LED, or all PC LED overrides. |
| 3 | Keepalive | Renews the active override session timeout. |

Targets:

| Value | Target | Notes |
| --- | --- | --- |
| 0 | Gimbal rings | Preserves the existing command: changes physical LEDs `6..25`. |
| 1 | Individual LED | Uses byte 6 as the physical strip index `0..25`. LEDs `0..5` are outside the rings. |
| 2 | All PC overrides | Valid for Release only; clears the ring override and every individual LED override. |

For an individual LED, Set color uses bytes 3–5 for RGB and byte 6 for its
physical index. Release with target 1 uses byte 6 to restore that LED to the
firmware's current color. Individual LED overrides take priority over the
uniform ring override. Releasing the ring leaves individual LED overrides in
place; releasing all clears both kinds.

Overrides expire after 5 seconds without a Set color or Keepalive command.
The normal joystick HID input report is unchanged.
