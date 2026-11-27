<!--
  Source: https://n64brew.dev/wiki/RDRAM
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

Rambus DRAM (or '''RDRAM''') is a type of synchronous dynamic random-access memory (SDRAM) designed by [[w:Rambus|Rambus]]. The N64 motherboard came with either one or two chips, totaling 4 MiB (4,194,304 bytes) of general purpose storage which can be accessed by the CPU. The optional [[Expansion Pak]] could increase this by an additional 4 MB and is required for some games to run.

Each byte of RDRAM actually has an extra bit, which can only be used by the RDP and VI core. This 9th bit is used to store things like anti-aliasing coverage in the color buffer. On systems other than the N64, the 9th bit would likely be used for parity checks.

= RDRAM system overview =

A typical RDRAM system is composed of 3 main elements :

* a controller, which act as the channel master. This role is fulfilled by the [[RDRAM Interface|RI]] with the help of the RAC (Rambus ASIC Cell).
* the channel, which is a synchronous bus connecting the RDRAM devices together.
* RDRAM modules, each containing memory banks, and some registers. RDRAM devices are daisy-chained via serial signals SIn/SOut.

[[File:RI RDRAM png.png|center|frame|RI/RDRAM system overview]]
The N64 system implements the "Base RDRAM" protocol, which is the earliest version of RDRAM protocol. Historical note, latter version of the protocol are "Concurrent RDRAM" and "Direct RDRAM".

All known retail units use 2 MiB RDRAM modules, both within the console and within the expansion pak. There are no proof that 1 MiB RDRAM modules were ever produced and sold (preliminary datasheets can be found online, but there is no proof they ever went to production). Moreover, [https://github.com/decompals/N64-IPL/blob/697693854124e1a62e8550d0f21598a7ee4e5314/src/ipl3.s#L339-L344 a bug has been found] in the official Nintendo IPL3 code (in charge of RDRAM initialization) that would prevent 1 MiB modules from working. The code seems designed to handle those, but then it was probably never actually tested and in fact it would not work. This is another proof that 1 MiB modules were never used on Nintendo official parts, because if they were, the existing games would not boot on them because of this bug.

= Interface Pinouts =
{| class="wikitable"
|+
!Pin
!Signal
!RSL
!I/O
!Description
|-
|1
|VDD
|
| -
|<nowiki>+3.3V power supply.</nowiki>
|-
|2
|GND
|
| -
|Circuit ground.
|-
|3
|DQ8
|Y
|I/O
|Signal line (bit 8) for REQ, DIN, and DOUT packets.
|-
|4
|GND
|
| -
|Circuit ground.
|-
|5
|DQ7
|Y
|I/O
|Signal line (bit 7) for REQ, DIN, and DOUT packets.
|-
|6
|NC*
|
| -
|Not connected.
|-
|7
|ADDRESS
|Y
|I
|Signal line for COL packets with column addresses.
|-
|8
|VDD
|
| -
|<nowiki>+3.3V power supply.</nowiki>
|-
|9
|DQ6
|Y
|I/O
|Signal line (bit 6) for REQ, DIN, and DOUT packets.
|-
|10
|GND
|
| -
|Circuit ground.
|-
|11
|DQ5
|Y
|I/O
|Signal line (bit 5) for REQ, DIN, and DOUT packets.
|-
|12
|VDDA
|
| -
|Separate analog power supply for clock generation in the RDRAM.
|-
|13
|RXCLK
|Y
|I
|Receive clock. All input packets are aligned to this clock.
|-
|14
|GNDA
|
| -
|Separate analog ground for clock generation in the RDRAM.
|-
|15
|TXCLK
|Y
|I
|Transmit clock. DOUT packets are aligned with this clock.
|-
|16
|VDD
|
| -
| +3.3V power supply.
|-
|17
|DQ4
|Y
|I/O
|Signal line (bit 4) for REQ, DIN, and DOUT packets.
|-
|18
|GND
|
| -
|Circuit ground.
|-
|19
|COMMAND
|Y
|I
|Signal line for REQ, RSTRB, RTERM, WSTRB, WTERM, RESET, and CKE packets. 
|-
|20
|SIN
|
|I
|Initialization daisy chain input. CMOS levels. See section on initialization for more details.
|-
|21
|VREF
|
|I
|Logic threshold reference voltage for RSL signals.
|-
|22
|SOUT
|
|O
|Initialization daisy chain output. CMOS levels. See section on initialization for more details.
|-
|23
|DQ3
|Y
|I/O
|Signal line (bit 3) for REQ, DIN, and DOUT packets.
|-
|24
|GND
|
| -
|Circuit ground.
|-
|25
|DQ2
|Y
|I/O
|Signal line (bit 2) for REQ, DIN, and DOUT packets.
|-
|26
|NC
|
| -
|Not connected.
|-
|27
|DQ1
|Y
|I/O
|Signal line (bit 1) for REQ, DIN, and DOUT packets.
|-
|28
|GND
|
| -
|Circuit ground.
|-
|29
|DQ0
|Y
|I/O
|Signal line (bit 0) for REQ, DIN, and DOUT packets.
|-
|30
|NC
|
| -
|Not connected.
|-
|31
|GND
|
| -
|Circuit ground.
|-
|32
|VDD
|
| -
| +3.3V power supply.
|}
RSL stands for Rambus Signaling Levels, a low-voltage-swing, active-low signaling technology.

Source: Rambus concurrent RDRAM datasheet [https://web.archive.org/web/19970101123304if_/http://www.rambus.com:80/docs/1664mcds.pdf]

= RDRAM registers =

{| class="wikitable"
|+ Register summary
|-
! Number 
!CPU Addr[9:0]!! Name !! Description
|-
| 0 
|0x000|| DeviceType || Read-only register which describes RDRAM configuration
|-
| 1 
|0x004|| DeviceId || Specifies base address of RDRAM
|-
| 2 
|0x008|| Delay || Specifies CAS timing parameters
|-
| 3 
|0x00C|| Mode || Control operating mode and I<sub>OL</sub> output current
|-
| 4 
|0x010|| RefInterval || Specifies refresh interval for devices that require refresh
|-
| 5 
|0x014|| RefRow || Next row and bank to be refreshed
|-
| 6 
|0x018|| RasInterval || Specifies RAS access interval
|-
| 7 
|0x01C|| MinInterval || Provides minimum delay information and some special control
|-
| 8 
|0x020|| AddressSelect || Specifies Adr field subufield swapping to maximize hit rate
|-
| 9 
|0x024|| DeviceManufacturer || Read-only register providing manufacturer and device information
|-
| 128 
|0x200|| Row || Address of currently sensed row in each bank
|}

RDRAM registers mirror every 0x40 bytes (16 words). Register numbers 10 to 15 all produce 0 when read. Above 0x200 (register number 128) the Device Type mirrors are replaced with the Row register.

See [[RDRAM Interface|RI page]] for more details about how RDRAM registers are mapped into CPU address space.

'''Reset and initialization:'''

* After RDRAM device reset, '''Delay''' needs to be set correctly before anything will work, see '''[[RDRAM#Reset Complications|Reset Complications]]'''
* After reset all devices will respond to Broadcast writes. Only the closet device in the Sin/Sout chain will respond to a non-broadcast write. 
* Before the device will respond to Register reads, each device needs to be assigned a '''DeviceId''' and enabled by setting '''Mode's''' DeviceEnable bit.
* After each device has been enabled, the next device in the Sin/Sout chain will respond now respond to non-broadcast writes. 
* Register reads will not return the correct value until the after the device's current control calibration as finished.

'''Endianness:''' 

Rambus devices are little endian. Doesn't matter for regular memory, but that does mean registers are all byte swapped. The register descriptions below have been remapped to show big endian bit offsets.  

'''Address alignment issues:'''

The Rambus register commands (Wreg, WregB and Rreg) are defined to be  "Quadbyte" (32bit) transfers, and so expect the data to be in the first 4 bytes.But RI only supports transfers with 1 to 16 "Octbyte" (64 bits). This works fine for accessing registers with "even" addresses (when <code>Addr[2] == 0</code>), as the value is already mapped to the first 4 bytes of the read/write data packet. But when accessing "odd" registers (when<code>Addr[2] == 1</code>), the value ends up bytes 4-7 of the Octbyte transfer, which gets ignored.

''Note: Because RCP is big endian, it puts 32bit even addresses in the Upper half of the 64bit word, and 32bit odd addresses in the lower half, RI outputs the MSB first, so it ends up in byte 0 of the Rambus data packet.'' 

[[MIPS Interface#0x0430 0000 - MI MODE|MI MODE]]'s '''Upper mode''' is used work around this problem, as it forces MI to always map the value into the upper half of DBus, which results in the value always mapping to bytes 0-3 of the "Octbyte" transfer, while still passing the original address through. Nintendo's IPL3 compulsively wraps all accesses to RDRAM register with writes to MI_MODE's SetUpper/ClearUpper. But you only actually need Upper Mode for accessing the "odd" registers. 

'''NOTE:''' In the following register description we will omit the ninth bit which is unused when accessing RDRAM registers, and describe them as a 32bit word instead of 4x{8,9}bit.

==== <span style="display:none;">0x00 - DeviceType ====
----
{{#invoke:Register table|head|600px|DeviceType <code>0x00</code>}}
{{#invoke:Register table|row|31:24}}
| R-? || R-? || R-? || R-? || U-0 || R-1 || U-0 || R-?
|-
| colspan="4" | ColumnBits || — || Bn || — || En
{{#invoke:Register table|row|23:16}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="4" | BankBits || colspan="4" | RowBits
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| R-0 || R-0 || R-0 || R-? || R-0 || R-0 || R-0 || R-0
|-
| colspan="4" | Version || colspan="4" | Type
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-28 | ColumnBits | Number of column address bits, or said differently, declares that this RDRAM device has 2^ColumnBits bytes per row.
| 26 | Bn | Bonus, number of bits per byte. <br>0 {{=}} 8bit byte<br>1 {{=}} 9bit byte
| 24 | En | Enhanced speed grade. <br>0 {{=}} Normal<br> 1 {{=}} Low Latency
| 23-20 | BankBits | Number of bank address bits, or said differently, declares that this RDRAM device has 2^BankBits banks.
| 19-16 | RowBits | Number of row address bits, or said differently, declares that this RDRAM devices has 2^RowBits rows per bank.
| 7-4 | Version | RDRAM version. <br>0001 {{=}} Extended architecture (Base RDRAM protocol)<br>0010 {{=}} Concurrent RDRAM device (not used on N64, as far as we know).
| 3-0 | Type | Device type. <br>0000 {{=}} RDRAM device
}}

==== <span style="display:none;">0x01 - DeviceId ====
----
{{#invoke:Register table|head|600px|DeviceId <code>0x01</code>}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-0 || U-0
|-
| colspan="6" | IdField[25:20] || — || —
{{#invoke:Register table|row|23:16}}
| RW-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| IdField[26] || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | IdField[34:27]
{{#invoke:Register table|row|7:0}}
| RW-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| IdField[35] || — || — || — || — || — || — || —
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 7,15-8,23,31-26 | IdField[35:k] | Compared to AdrS[35:k] to select RDRAM.<br>k {{=}} 21 for 16/18Mbit RDRAM.<br>k {{=}} 20 for 8/9Mbit RDRAM.<br>That is, bit 20 is ignored for 2 MiB RDRAM modules (which means that they can only be mapped to even device IDs and thus aligned to their size).
}}

==== <span style="display:none;">0x02 - Delay ====
----
{{#invoke:Register table|head|600px|Delay <code>0x02</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || RW-1 || RW-0 || RW-0 || R-0 || R-1 || R-1
|-
| — || — || colspan="3" | AckWinDelay || colspan="3" | AckWinBits
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || RW-0 || RW-0 || RW-1 || R-0 || R-1 || R-1
|-
| — || — || colspan="3" | ReadDelay || colspan="3" | ReadBits
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || RW-0 || RW-0 || R-0 || R-1 || R-0
|-
| — || — || — || colspan="2" | AckDelay || colspan="3" | AckBits
{{#invoke:Register table|row|7:0}}
| U-0 || U-0 || RW-1 || RW-0 || RW-0 || R-0 || R-1 || R-1
|-
| — || — || colspan="3" | WriteDelay || colspan="3" | WriteBits
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 29-27 | AckWinDelay[2:0] | Adjusts the size of the acknowledge window. Normally set to 5 {{=}} 101b.<br>101b {{=}} 5 tcycles<br>110b {{=}} 6 tcycles<br>111b {{=}} 7 tcycles<br>000b {{=}} 8 tcycles<br>001b {{=}} 9 tcycles<br>010b {{=}} 10 tcycles<br>011b {{=}} 11 tcycles<br>100b {{=}} 12 tcycles
| 26-24 | AckWinBits[2:0] | Read-only. Number of bits of AckWinDelay (3).
| 21-19 | ReadDelay[2:0] | Delay between end of request and start of Read data packet. Normally set to 7 {{=}} 111b. Defaults to 8 {{=}} 001b after reset. <br>111b {{=}} 7 tcycles<br>000b {{=}} 8 tcycles<br>001b {{=}} 9 tcycles<br>010b {{=}} 10 tcycles<br>011b {{=}} 11 tcycles<br>100b {{=}} 12 tcycles<br>101b {{=}} 13 tcycles<br>110b {{=}} 14 tcycles
| 18-16 | ReadBits[2:0] | Read-only. Number of bits of ReadDelay (3).
| 12-11 | AckDelay[1:0] | Delay between end of request and start of Ack data packet. Normally set to 3 {{=}} 11b.<br>11b {{=}} 3 tcycles<br>00b {{=}} 4 tcycles<br>01b {{=}} 5 tcycles<br>10b {{=}} 6 tcycles
| 10-8 | AckBits[2:0] | Read-only. Number of bits of AckDelay (2).
| 5-3 | WriteDelay[2:0] | Delay between end of request and start of Write data packet. Normally set to 1 {{=}} 001b. Defaults to 4 {{=}} 100b after reset.<br>001b {{=}} 1 tcycles<br>010b {{=}} 2 tcycles<br>011b {{=}} 3 tcycles<br>100b {{=}} 4 tcycles<br>101b {{=}} 5 tcycles<br>110b {{=}} 6 tcycles<br>111b {{=}} 7 tcycles<br>000b {{=}} 8 tcycles
| 2-0 | WriteBits[2:0] | Read-only. Number of bits of WriteDelay (3).
}}

===== '''Reset Complications''' =====
RI is hardwired to use a write delay of 1 TCycle, this means the Write request packet is send starting from (TCycle 0, RCP Cycle 0), finishing after 3 TCycles. 64bits of Data is send starting at (TCycle 4, RCP Cycle 1), finishing at (TCycle7, RCP Cycle 1.75)

But the WriteDelay defaults to 4 TCycles after reset ''(probably<sup>[1]</sup>)'', Attempting to write a register will result in the Rambus device sampling 32bits of data during TCycles 7 and 8 (which is RCP Cycle 1.75 and 2.0), which is too late, It's going to be zeros or some other garbage.

Before we can do anything else at all, we need to somehow set the WriteDelay to the correct value of 001b, despite the fact the WregB command results in the Rambus device reading garbage. <Br>IPL3 gets around this problem by using MI's Repeat mode (called "Init mode" in some documentation), see [[MIPS_Interface#0x0430_0000_-_MI_MODE|MI_MODE]] for more details about MI's various modes. 

By configuring a 16 byte repeat (<code>MI_MODE_REG] = 0x10f</code>), the next word written to an Rambus device register (or memory) will be repeated over 16 bytes. This causes RI to emit a 128bit burst request, with the data on the bus during TCycle 4-11. As the Rambus device is sampling the bus during TCycle 7 and 8, it will get valid data we control. <Br>But it's reading data halfway between two words. So IPL3 has to rotate the value by 16 bits to get the correct result. It wants to write <code>0x2838_1808</code>, but it actually writes <code>[0xA3F80000 + RDRAM_DELAY_REG] = 0x1808_2838</code>.

After updating WriteDelay with a broadcast write to all device, all future operations will have the correct timings. 

''<sup>[1]</sup> The Toshiba 8Mbit datasheet confirms this as the default. It default to 4, because some devices (like the Toshiba 18Mbit) only have 2 bits, so can only support a maximum write delay of 4. Devices with more bits default to 0b100 for compatibility.''

==== <span style="display:none;">0x03 - Mode ====
----
{{#invoke:Register table|head|600px|Mode <code>0x03</code>}}
{{#invoke:Register table|row|31:24}}
| RW-1 || RW-1 || RW-0 || R-0 || RW-0 || RW-1 || RW-0 || RW-0
|-
| CE || X2 || PL || SV || SK || AS || DE || LE
{{#invoke:Register table|row|23:16}}
| RW-1 || RW-1 || U-0 || U-0 || RW-0 || U-0 || U-0 || U-0
|-
| C5 || C2 || — || — || AD || — || — || —
{{#invoke:Register table|row|15:8}}
| RW-1 || RW-1 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| C4 || C1 || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| RW-1 || RW-1 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| C3 || C0 || — || — || — || — || — || —
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31 | CE / CCEnable| Current Control Enable.<br>0 {{=}} manual<br>1 {{=}} auto
| 30 | X2 / CCMult | Should be 1. Inverted when read. (Toshiba datasheet states that it select wether X<sub>1</sub> or X<sub>2</sub> register is used for the current control register).
| 29 | PL | Select PowerDown Latency
| 28 | SV / SkipValue | For tests. 0
| 27 | SK / Skip| For tests. 0
| 26 | AS / AutoSkip | For tests. 1
| 25 | DE / DeviceEnable | Enable RDRAM device. When disabled, only broadcast register requests can be executed.<br>0 {{=}} disabled<br>1 {{=}} enabled
| 24 | LE | Enable PowerDown mode for RDRAM that supports it to reduce power consumption.
| 19 | AD / AckDis | For low latency RDRAM only. Allows to supress acknowledge response when set to 1.
| 23,15,7,22,14,6 | C[5:0] / CCValue | Current Control value which controls ''in fine'' the output current I<sub>OL</sub>.<br>In manual mode (CE{{=}}0), I<sub>OL</sub> is proportional to (63-CC) with I<sub>OL</sub> ~ (0.95±0.3)×(63-CC) mA, for CC {{=}} 0..63. (These coefficients derive from Imax±△/63 and vary between models)<br>This field is inverted when read.<br>In auto mode (CE{{=}}1), I<sub>OL</sub> is proportional to (63-CC) with I<sub>OL</sub> ~ (1.25±0.1)×(63-CC) mA, for CC {{=}} 31..63. (These coefficients derive from I<sub>40</sub>±△/(63-31) and vary between models)<br>An internally generated value is returned when read.
}}

==== <span style="display:none;">0x04 - RefInterval ====
----
{{#invoke:Register table|head|600px|RefInterval <code>0x04</code>}}
{{#invoke:Register table|row|31:24}}
| ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-?
|-
| colspan="8" | ?
{{#invoke:Register table|row|23:16}}
| ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-?
|-
| colspan="8" | ?
{{#invoke:Register table|row|15:8}}
| ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-?
|-
| colspan="8" | ?
{{#invoke:Register table|row|7:0}}
| ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-? || ?-?
|-
| colspan="8" | ?
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-0 | ? | Unknown format
}}

==== <span style="display:none;">0x05 - RefRow ====
----
{{#invoke:Register table|head|600px|RefRow <code>0x05</code>}}
{{#invoke:Register table|row|31:24}}
| RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || U-0
|-
| colspan="7" | RowField[7:1] || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || RW-? || U-0 || U-0 || U-0
|-
| — || — || — || — || BankField || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-? || RW-?
|-
| — || — || — || — || — || — || colspan="2" | RowField[9:8]
{{#invoke:Register table|row|7:0}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 9-8,31-25 | RowField | Current row being refreshed.
| 19 | BankField | Current bank being refreshed.
}}

This register is normally read or written only for testing purpose.

==== <span style="display:none;">0x06 - RasInterval ====
----
{{#invoke:Register table|head|600px|RasInterval <code>0x06</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| — || — || — || colspan="5" | RowPrecharge[0:4]
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| — || — || — || colspan="5" | RowSense[0:4]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| — || — || — || colspan="5" | RowImpRestore[0:4]
{{#invoke:Register table|row|7:0}}
| U-0 || U-0 || U-0 || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| — || — || — || colspan="5" | RowExpRestore[0:4]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 24-28 | RowPrecharge | Specify RowPrecharge timing.
| 16-20 | RowSense | Specify RowSense timing.
| 8-12 | RowImpRestore | Specify RowImpRestore timing.
| 0-4 | RowExpRestore | Specify RowExpRestore timing.
}}

NOTE: all fields are in bit reversed order (bit 4 is LSB, bit 0 is MSB).

==== <span style="display:none;">0x07 - MinInterval ====
----
{{#invoke:Register table|head|600px|MinInterval <code>0x07</code>}}
{{#invoke:Register table|row|31:24}}
| R-0 || R-0 || R-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| MAD[3] || MRD[3] || MWD[3] || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| R-0 || R-1 || R-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| MAD[2] || MRD[2] || MWD[2] || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| R-1 || R-1 || R-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| MAD[1] || MRD[1] || MWD[1] || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| R-1 || R-1 || R-1 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| MAD[0] || MRD[0] || MWD[0] || colspan="5" | SpecFunc[4:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31,23,15,7 | MinAckDelay | Minimum of AckDelay of RDRAM.
| 30,22,14,6 | MinReadDelay | Minimum of ReadDelay of RDRAM.
| 29,21,13,5 | MinWriteDelay | Minimum of WriteDelay of RDRAM.
| 4-0 | SpecFunc | Performs various commands when written, see table below.
}}

As SpecFunc is the only writable field in the register, you can just write the command.

'''SpecFunc Commands:'''
{|
| <code>00000</code> || - '''Nop''' || - Do nothing 
|-
| <code>xxxx1</code> || - '''SetRR''' ||- Manual refresh. The device immediately preforms a single a burst refresh of two rows per bank
|-
| <code>x0x10</code> || - '''ClrRE''' || - Disable automatic refresh 
|-
| <code>x01xx</code> || - '''SetPD''' || - Enter the powerdown state
|-
| <code>×1x0x</code> || - '''SetRE''' || - Enable automatic refresh
|-
| <code>1xxxx</code> || colspan="2" | - '''Reserved'''
|}

''The N64 implements refresh by broadcasting one SetRR command whenever VI emits a horizontal sync pulse.''

==== <span style="display:none;">0x08 - AddressSelect ====
----
{{#invoke:Register table|head|600px| AddressSelect <code>0x08</code>}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-?
|-
| colspan="7" | SwapField[6:0] || -
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-? || U-? || U-? || RW-0 || RW-0
|-
| - || - || - || - || - || - || colspan="2" | SwapField[8:7]
{{#invoke:Register table|row|15:8}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| - || - || - || - || - || - || - || -
{{#invoke:Register table|row|7:0}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| - || - || - || - || - || - || - || -
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-25,16-15 | SwapField | Each bit swaps two bits of the address. When all bits are 0, there is no swaping.
}}

'''Extra Details:''' 
: The address swapping feature allows banks to be interleaved. For example, Bank 0 row 0 can be followed by Bank 1 row 0 and so on. <br> This can improve performance for many memory access patterns.

: However, RI doesn't appear to support this feature. It expects Bank zero to be in the first megabyte of address space, Bank one in the second megabyte, and so on. 

==== <span style="display:none;">0x09 - DeviceManufacturer ====
----
{{#invoke:Register table|head|600px| DeviceManufacturer <code>0x09</code>}}
{{#invoke:Register table|row|31:24}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="8" | ManufactureCode[7:0]
{{#invoke:Register table|row|23:16}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="8" | ManufactureCode[15:8]
{{#invoke:Register table|row|15:8}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="8" | Manufacture[7:0]
{{#invoke:Register table|row|7:0}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="8" | Manufacture[15:8]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-24,23-16 | ManufactureCode | Manufacture is allowed to put whatever they want here?
| 15-8,7-0 | Manufacture | Code specifying the manufacturing company, see table below.
}}

{|
|-
! Manufacture !! ID Code
|-
| Toshiba || <code>0x0002</code>
|-
| Fujitsu || <code>0x0003</code>
|-
| NEC || <code>0x0005</code>
|-
| Hitachi || <code>0x0007</code>
|-
| Oki || <code>0x0009</code>
|-
| LG Semicon || <code>0x000a</code>
|-
| Samsung || <code>0x0010</code>
|-
| Hyundai || <code>0x0013</code>
|}

= RDRAM addressing =
Warning : In this paragraph, we describe RDRAM addressing within the RDRAM protocol. This is not to be confused with RDRAM addresses "as seen" by the CPU or RCP. See [[RDRAM Interface#Memory address|RI memory addressing]] paragraph for details about how the RI converts addresses between the two address spaces.

RDRAM protocol addresses RDRAM memory and registers using a 36bit address and a variety of commands :

* many types of memory read
* many types of memory write
* register read
* register write
* broadcast register write (all connected RDRAM will write the same value to the specified register)

The higher part of the address identify an RDRAM device, the lower part is an offset within the device (in register-space for register commands, and memory space for memory commands).

The procedure of identifying which RDRAM device is addressed by a given command + address is call Id matching.

It works as follow:

Given a 36 bit address Adr[35:0], we compute a "partially bit-swapped" AdrS[35:0] such that bits [28:20] and bits [19:11] are swapped on a bit by bit bases based on the value of SwapField (from AddressSelect register). Bits [35:29] and [10:0] are left untouched. This swapping of bits provides a flexible way of remapping addresses across banks of a given device and across devices to benefit from internal row caching. This can help increase DRAM hit rate in several applications.

The upper 16 bits (or 15bits for 2x{8,9}Mbit devices) of AdrS are then compared to IdField contained in DeviceId register. If both are equal the RDRAM device has a Id Match.

More formally this can be written as follow :
 <code>AdrS[35:29] = Adr[35:29]</code>
 <code>AdrS[28:20] = ( SwapField[8:0] & Adr[19:11]) | (~SwapField[8:0] & Adr[28:20])</code>
 <code>AdrS[19:11] = (~SwapField[8:0] & Adr[19:11]) | ( SwapField[8:0] & Adr[28:20])</code>
 <code>AdrS[10:0] = Adr[10:0]</code>
 <code>IdMatch = AdrS[35:M] == IdField[35:M]</code>
 <code>with M = 21 for 2x{8,9]Mbit modules, M=20 for 1x{8,9}Mbit modules.</code>
Remark : An IdMatch doesn't mean necessarily that the RDRAM device will act on the request, and conversely a non matching RDRAM device can still act on a request. Other factors such as DeviceEnable bit from ModeRegiter, SIn pinout can inhibit a request, and the broadcast register write can force a request even on non matching RDRAM device.

= Current Control calibration =
Any RDRAM device (module and controller) wishing to "talk" on the RDRAM channel must configure its output current I<sub>OL</sub> controlled by the current control ('''CC''' for short) register.

2 modes are possible to configure the current control register :

# Manual mode. In this mode, the value of the current control register is linearly correlated to I<sub>OL</sub>, such that I<sub>OL</sub> @ CC=63 -> 0mA, and I<sub>OL</sub> @ CC=0 -> I<sub>max</sub> (I<sub>max</sub> will vary between RDRAM due to process differences).  In this mode, fluctuation due to temperature, change over time and are not compensated, so it may require a manual periodic readjustment. Note also that, in this mode, the CC register value read will be inverted.
# Automatic mode. In this mode, small fluctuations are automatically corrected, so no further readjustment should be required. The relation between CC value and I<sub>OL</sub> is still mostly linear but with a different slope. Note also that, in this mode, the CC register value read will be an internally generated one, not the one used to program the CC register.

The purpose of the CC calibration procedure is to find the CC value in Automatic mode that maximize the signal margin.

One possible approach to do so is described below :

We define the quantity CCi = 63-CC (= CC^63 = CC "inverted") which is more natural to use because I<sub>OL</sub> is proportional to CCi.

We define a memtest80 function which writes an octbyte with all bits set to '1' (eg. UINT64_C(0xffffffffffffffff)) at the start of the RDRAM device to test, and read back the 6th byte of the previously written octbyte. It then counts how many bits were set. This write / readback is done 10 times, and the cumulated number of '1' bits read is returned. For a non calibrated RDRAM device, the number is less than 80 (eg. the device can't always transfer back '1' because of inadequate V<sub>OL</sub>). Basically, the returned value gives a score (over 80) of the quality of the RDRAM device transmission with the current CC value.

1. Estimate the value of CCi in manual mode which gives a V<sub>OL</sub> almost equal to V<sub>REF</sub>.
This can be done by writing increasing CCi values in manual mode and accumulating the weighted difference CCi * (memtest80 - previous_memtest80) for CCi = 0..N (N being the first value of CCi which allows to read all 80 bits during memtest80; N <= 63).
This weighted sum of CCi*(memtest80-previous_memtest80) for CCi = 0..N, divided by 80 (minus 0.5 to account for accumulation/rounding errors) is an estimate of CCi which gives V<sub>OL</sub> ~ V<sub>REF</sub>.

2. Multiply this value by 2.2: doubling the CCi value, with 10 percent margin, should give a reasonable estimate of CCi such that V<sub>OL</sub> is symmetric to V<sub>OH</sub> with respect to V<sub>REF</sub> (eg. it maximizes signal margin).

3. Convert the obtained manual CCi value to auto CCi. Here the procedure is again iterative and tries to find the value CCi to write in Auto mode which minimizes the absolute difference between the CCi value read in auto mode (remember this is an internally generated value different from the CCi value written) and the target manual CCi.
   
4. Repeat this whole procedure 4 times and average the obtained auto CCi value.

In practice steps 1., 2. and 3. avoid usage of floating points and rescale some values with an appropriate scaling factor (here 80x10) to avoid loss of precision due to integer computations.

= Known RDRAM Console Chip Configurations =
{| class="wikitable"
|+
!N64 Version
!Board revision
!Region
!Number of RDRAM Chips
!Size per Chip(Mbytes)
!Size per Chip(Mbits)
|-
|NUS-001
|(P) - 01
|PAL
|2
|2.25Megabytes
|18Mbit 
|-
|NUS-002
|(P) - 02
|PAL
|1
|4.5Megabytes
|36Mbits
|}

= Known RDRAM Expansion Pak Configurations =
{| class="wikitable"
|+
!Expansion Pak Type
!Number of RDRAM Chips
!Size per Chip(Mbytes)
!Size per Chip(Mbits)
|-
|Jumper Pak (Nintendo Official)
|0
|0
|0
|-
|Expansion Pak (Nintendo Official)
|1
|4.5Megabytes
|36Mbits
|}
There are 3rd party Expansion Paks that have 2 chips which are both 2.25Megabytes each. Please provide images and makers here.

= Initialization Sequence =
This Initialization sequence is based on the 6102 CIC boot code

'''[[:File:Cncrntug.pdf|File:Cncrntug.pdf]]'''


RDRAM Initialization procedure as implemented in IPL3:


   1. a. Enable RI Auto Current
      b. let it settle by waiting using countdown(8800)
      c. load RI CC value
   2. Enable RI T/R select
   3. a. Force RI_MODE reset, disable R/T stop
      b. wait using countdown(4)
   4. a. Force RI_MODE standby, enable R/T stop
      b. wait using countdown(32)
   5. a. Set MI INIT mode + length=15 by writing 0x10f to [MI_MODE_REG]
      b. Setup all RDRAM delays (AckWin=5,Read=7,Ack=3,Write=1) by writing 0x18082838 to [0xa3f80004] [bcast]
   6. a. Setup all RDRAM refresh row to 0 [bcast]
      b. Move all RDRAM modules to top of address space deviceid = 0x80000000 [bcast]
   7. a. compute rdram reg space size (reg_step) based on RCP version (RCPv1: 128, RCPv2: 256)
      b. init top rdram reg pointer (RDRAM_REGS_BASE + 32 * reg_step)
   8. First pass which walk through at most 8 RDRAMs and for valid ones:
      a. place them at next 2MB boundary (eg. rdram_deviceid = i * 0x08000000)
      b. compute optimal (auto) current calibration value for RDRAM module and apply it
      c. exit first pass loop if cc value is zero, eg. no RDRAM module is present
      d. read device description registers (device_type + manufaturer). These reads must be surrounded by MI_MODE= SET_DRAM_REG and CLR_DRAM_REG because individual rdram registers are accessed.
      e. based on device description, setup optimal RAS timing
      f. store RDRAM parameters (CC, geometry {eg. col, bank, row fields from device_type}) for second pass
      g. update values which tracks how to reorder all 2MB RDRAM modules before the 1MB, how many modules are effectively presents and the 2MB_bitfield (=2^(number of 2MB modules)-1, because all 2MB banks will be placed first)
   9. a. Disable all RDRAM modules (rdram_mode = 0xc4000000) [bcast]
      b. and move them all back to top of address space (rdram_deviceid = 0x80000000) [bcast]   
   10. Second pass iterate through all modules discovered during the first pass and:
      a. reorder them so that all 2MB modules are placed before 1MB modules
      b. write previously computed optimal CC for each module
      c. touch RDRAM modules to settle their timing circuits.
         1MB modules undergo 4 consecutive reads (ptr+k*0x00080000, k=0..1) x 2
         2MB modules undergo 8 consecutive reads (ptr+k*0x00080000, k=0..3) x 2    
   11. a. setup RI refresh register = 0x63634 | 2MB_bitfield << 19
      b. do a dummy read of RI refresh reg    
   12. Return amount of detected RDRAM.

Trivia: there is very likely a copy-paste error in the original IPL3 code when incrementing t6 in the second pass. It should have been t8 so we can place next 1MB module at next slot. But I guess it went unnoticed because retail models don't use 1MB modules.

= Expansion Pak Detection =
The typical way to detect how much memory is installed is to probe it.

LibUltra provides a function called osGetMemSize() which does this. The function writes different values at addresses in the uncached KSEG1 direct map, starting at 0xa0300000, and then reads the values back. It tries successively higher addresses, jumping by 1 MB each time through the loop. It returns the amount of RAM which it successfully wrote and read back, rounded up to a number of megabytes.

 // C-like pseudocode...
 u32 osGetMemSize(void) {
     // Base address of RAM in kseg1.
     uintptr_t base_addr = 0xa0000000;
     uintptr_t megabyte = 1024 * 1024;
     // Address where we will probe.
     uintptr_t cur_addr = kseg1 + 3 * megabyte;
     while (true) {
         write to addr;
         read from addr;
         if (value read != value written) {
             break;
         }
         cur_addr += megabyte;
     }
     return cur_addr - base_addr;
 }

During boot, IPL3 will also write the amount of RAM available, in bytes, to a 32-bit value at address 0x80000318 (or 0x800003f0, for CIC 6105). On retail hardware, this should always have the value 0x400000 (no expansion pak) or 0x800000 (expansion pak). When using LibUltra, this variable can be accessed with the name osMemSize, which is defined like this:

 extern u32 osMemSize;

LibDragon provides the the amount of memory installed with the get_memory_size() function.

= Drawbacks and Limitations =
==== Opinion ====
{{Blockquote
|text=RDRAM has excellent data transfer speed for the era (bytes per second) but due to the protocol used and serial interface, memory transactions were somewhat slower (how much time it took from starting a read/write operation to finishing it). In practice, you may find that the available memory bandwidth is a limiting factor for the performance of your game.
See: [https://retrocomputing.stackexchange.com/questions/17564/how-fast-was-rambus-compared-to-regular-edo-ram How fast was Rambus compared to regular EDO RAM?]
|author=Vanadium
}}

= Datasheets =
Several manufacturers produced compatible "Base RDRAM" modules such as :

* [https://www.datasheetarchive.com/pdf/download.php?id=ba4c2602c3e903353ab08f0b5ce7b7ba8aff76&type=O&term=GM73V1892AH16L LG GM73V1892AH16L]
* [https://www.datasheetarchive.com/pdf/download.php?id=80d868b3d8d4b492b8255b3cf45587bffb5c32&type=P&term=uPD488170L NEC uPD488170L]
* [https://www.datasheetarchive.com/pdf/download.php?id=98c391ce728eda7ff786fc9edfaa7c8d71859d&type=M&term=MSM5718B70 OKI MSM5718B70]
* [https://www.datasheetarchive.com/pdf/download.php?id=187da05b037831407d99bb6a7a103aa0d6dc80&type=O&term=TC59R1809 Toshiba TC59R1809VK TC59R1809HK (18Mbit chip)]
* [https://datasheet.datasheetarchive.com/originals/scans/Scans-067/DSA2IH00203571.pdf Toshiba TC59R0808HK (8Mbit chip)]

Reference : [https://bitbuilt.net/forums/index.php?threads/n64-expansion-paks-ram-part-numbers.3943/]
[[Category:Motherboard_components]]

= iQue Player =

The iQue Player replaced RDRAM with an off-the-shelf K4D263238E-GC33 16MiB DDR SDRAM differentially clocked at 192MHz for a peak bandwidth of up to 1536MB/s, about 3x that of N64's RDRAM. The bus latency is also much lower as it does not need to implement a packet protocol for transferring control signals, addresses and data over a small number of shared pins in the way RDRAM does; the SDRAM has a 32-bit data bus, a 12-bit address bus for both row and column addresses, and additional lines for other control signals.

However this SDRAM does not have an extra bit per byte as in RDRAM, this had to be emulated. This appears to have been achieved by halving the amount of available RAM to an effective 8MiB while using the remaining 8MiB to (very inefficiently) store coverage bits. The memory controller in the iQue Player SoC probably performs 2x32-bit transfers for each 32-bit word transferred, in which the first transfer contains the data and the second transfer contains coverage bits in the least significant bit of each byte. In the virtual memory map, addresses <code>0x81xxxxxx</code> can be accessed to bypass the memory controller's translation step to get a raw view of the memory, which looks like:
<pre>
           | 0x0                     | 0x4                       | 0x8                     | 0xC
-----------+-------------------------+---------------------------+-------------------------+---------------------------
0x81000000 | [32 bits at 0x80000000] | [Coverage for 0x80000000] | [32 bits at 0x80000004] | [Coverage for 0x80000004]
0x81000010 | [32 bits at 0x80000008] | [Coverage for 0x80000008] | [32 bits at 0x8000000C] | [Coverage for 0x8000000C]
...
</pre>

For example writing two words at <code>0x80000000</code> to:
<pre>
           | 0x0        | 0x4
-----------+------------+------------
0x80000000 | 0xFF00FF00 | 0x00FF00FF
</pre>
produces the following when read back at <code>0x81000000</code>:
<pre>
           | 0x0        | 0x4        | 0x8        | 0xC
-----------+------------+------------+------------+------------
0x81000000 | 0xFF00FF00 | 0x01000100 | 0x00FF00FF | 0x00010001
</pre>

Writing to <code>0x80000000</code> causes changes in both <code>0x81000000</code> and <code>0x81000004</code>. It is also possible to write directly to <code>0x81000000</code>: writing to data words are mirrored in <code>0x80000000</code> without disturbing coverage, while writing coverage leaves the corresponding data unchanged. If only using the CPU this allows all 16MiB of SDRAM to be used, however it is not very practical as it does not behave well with respect to DMA.
