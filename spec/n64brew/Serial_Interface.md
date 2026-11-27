<!--
  Source: https://n64brew.dev/wiki/Serial_Interface
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The Serial Interface (or '''SI''') is one of multiple I/O interfaces in the RCP, which is used to communicate with the [[PIF-NUS]] and in turn, [[Joybus Protocol|Joybus]] devices.

Memory mapped registers are used to configure the Serial Interface and initiate DMA reads and writes. The base address for these registers is <code>0x0480 0000</code>, also known as SI_BASE. However, because all memory accesses in the CPU are made using virtual addresses, the following addresses must be offset appropriately. For non-cached reads/writes, add <code>0xA000 0000</code> to the address. As an example, to directly write to the SI_DRAM_ADDR register, use address <code>0xA480 0000</code>.

In addition to these registers, SI is also in charge of handling the memory mapping of PIF-ROM and PIF-RAM to VR4300. These memories are mapped at physical address <code>0x1FC0 0000</code> (and normally accessed via the uncached segment at <code>0xBFC0 0000</code>).
== Mapped PIF-ROM and PIF-RAM ==
When the VR4300 access the physical area at <code>0x1FC0 0000</code> - <code>0x1FCF FFFF</code>, RCP handles the request via SI; the memory access performed via standard MIPS opcode like <code>LW</code> or <code>SW</code> is converted into a I/O communication with PIF, using the serial bus. See [[PIF-NUS#Internal ROMs and RAM]] for a description of the memories inside the PIF. 

The addresses are mapped as follows (and they mirror across the whole area): 
{| class="wikitable"
|+
|0x000 - 0x7BF
|PIF-ROM. This area contains the IPL1/IPL2 boot code. VR4300 starts running from these addresses after a NMI. During the boot process, PIF-ROM is locked out for security reasons, and during normal runtime all reads from these addresses return 0. 
|-
|0x7C0-0x7FF
|PIF-RAM (64 bytes). This area is used to communicate with PIF, mostly to run the Joyous protocol to communicate with external controllers.
|}
Notice that in general the SI is not aware of this memory map. For each access to the area, it will issue a read or write request (using the protocol detailed below) which includes the 11-bit address. It does not behave differently depending on the address (eg: writes to the ROM area are still issued). 

The SI serial protocol with PIF-NUS only allows to transfer 32-bit words (or 64-byte sequences, when a DMA transfer is requested), so it is advised for the VR4300 to access this memory mapped area only via 32-bit operations. The result obtained when using accesses of different size is detailed in [[Memory map#Range 0x1FC0'0000 - 0x1FCF'FFFF (SI external bus)]]. 

In general, read accesses are blocking, while write accesses are asynchronous. Read accesses while a write is in progress are correctly delayed and run at the end of the write. This is described in detail in [[Memory map#Range 0x1FC0'0000 - 0x1FCF'FFFF (SI external bus)]]. 

Direct writes to the memory mapped areas cause interrupts on the VR4300, exactly like DMA transfers. In fact, the two are mostly identical at the hardware level, including the fact that the flag DMA_BUSY is also set.

== DMA transfers ==
The SI allows to transfer the contains of the whole PIF-RAM (64 bytes) with a DMA transfer (both reads and writes). VR4300 can trigger these DMAs by writing to the registers <code>SI_PIF_AD_WR64B</code> and <code>SI_PIF_AD_RD64B</code> (see below).

Notice that the 64-byte read transfer has a special: when the transfer is requested by the SI, the PIF firmware first runs the whole joyous handshake described in PIF-RAM, communicating with the attached device; then t updates the contents of PIF-RAM with the results, and only a this point the ACK is sent to the SI and the actual transfer is done with the updated values. This means that the 64-byte DMA read is usually much slower than expected because it does not just transfer the bytes, but must first wait for the PIF to communicates with all controllers as requested.

== Communication protocol with PIF-NUS ==
[[File:SI - PIF communication protocol.gif|thumb|Visual representation of the protocol described in this paragraph]]

The communication protocol with PIF-NUS is the low-level data encapsulation performed by the SI to communicate with PIF-NUS. There are 4 supported packets:

* '''RD4B''' (Read 4 bytes): This packet is generated any time the VR4300 reads from the PIF mapped area. The SI sends on the bus the bits <code>11</code> to identify the packet, followed by bits 10..2 of the address to read (bits 1..0 are assumed to be always 0, that is the address is always 32-bit aligned). The PIF replies with an ACK followed by the 32-bit word that was contained in the memory (ROM or RAM) at the specified address.
* '''WR4B''' (Write 4 bytes): This packet is generated any time the VR4300 writes to the PIF mapped area The SI sends on the bus the bits <code>10</code> to identify the packet, followed by bits 10..2 of the address to write (bits 1..0 are assumed to be always 0, that is the address is always 32-bit aligned). The PIF replies with an ACK, and at that point the SI sends the 32-bit word to be written to memory (RAM; writes to ROM are obviously ignored) at the specified address. 
* '''RD64B''' (Read 64 bytes): This packet is generated any time the VR4300 issues a DMA read transfer The SI sends on the bus the bits <code>01</code>to identify the packet, followed by bits 10..2 of the address to write (which would normally be <code>111110000</code>, which are bits 10..2 of <code>0x7C0</code>). When the PIF receives this packet, it does not immediately replies with the ACK: first, it runs the joybus handshake described in PIF-RAM, communicating with the various attached devices, and updates the PIF-RAM contents with the result. Only after this is done, the ACK is sent to the SI, followed by the 512 bits of PIF-RAM contents. 
* '''WR64B''' (Write 64 bytes).  This packet is generated any time the VR4300 issues a DMA write transfer. The SI sends on the bus the bits <code>01</code>to identify the packet, followed by bits 10..2 of the address to write (which would normally be <code>111110000</code>, which are bits 10..2 of <code>0x7C0</code>). The PIF replies with an ACK, and at that point the SI sends the 512-bit sequence to be written to PIF-RAM.

== Registers ==
'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at power on
[x:y] = Specifies bits x to y, inclusively</pre>
==== <span style="display:none;">0x0480 0000 - SI_DRAM_ADDR ====
----
{{#invoke:Register table|head|550px|SI_DRAM_ADDR <code>0x0480 0000</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DRAM_ADDR[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DRAM_ADDR[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DRAM_ADDR[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-24 | Undefined | Initialized to <code>0</code>
| 23-0 | DRAM_ADDR[23:0] | RDRAM address used in SI DMAs
}}
==== <span style="display:none;">0x0480 0004 - SI_PIF_AD_RD64B ====
----
{{#invoke:Register table|head|550px|SI_PIF_AD_RD64B <code>0x0480 0004</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || — || colspan="3" | PIF_ADDR[10:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || R-0 || R-0
|-
| colspan="6" | PIF_ADDR[7:2] || 0 || 0
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-11 | Undefined | Initialized to <code>0</code>
| 10-0 | PIF_ADDR | Offset in PIF_RAM/PIF_ROM where to fetch data
}}

Writing to this register triggers a SI DMA transfer from PIF to RDRAM. The RDRAM address is the one stored in SI_DRAM_ADDR, while the address within PIF_ROM/PIF_RAM must be written to this register. Notice that the lowest two bits of the PIF address are fixed to zero, so only aligned transfers can be run.

This transfer is done by sending a RD64B serial packet to PIF, waiting for acknowledge and then writing to RDRAM the data sent back via serial. Notice that this command has a special meaning for PIF: if the PIF_RAM command byte has either bit 0 or bit 1 set, the respective commands will first be executed (both of them will write to PIF_RAM), and then the requested data is transferred. So the transfer could take a while to run, because the SI might be waiting for the acknowledge for a long time. See PIF-NUS for more information about RD64B.

In the normal case, VR4300 would have prepared a Joybus packet in PIF_RAM to poll controllers. When the SI DMA read is run, the PIF will receive the RD64B packet and will actually perform the full joybus exchange with controllers, writing the state in PIF_RAM. It will then send back the results to SI that will in turn write them to RDRAM. This means that the actual Joybus protocol is only executed when VR4300 asks to read the results via SI DMA, and the actual DMA will be delayed until the data is ready.

During the DMA transfer, SI_DRAM_ADDR is updated. At the end of the transfer, it points to the last word in RDRAM that was written to.

==== <span style="display:none;">0x0480 0008 - SI_PIF_AD_WR4B ====
----
{{#invoke:Register table|head|550px|SI_PIF_AD_WR4B <code>0x0480 0008</code>}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[31:24]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-0 | DATA | 32-bit data to be transferred to PIF-RAM
}}

This register is basically broken: it was probably meant to allow for a DMA transfer
of 4 bytes to PIF_RAM, but in reality it is just directly connected to an internal register of SI
holding the "current data" word for PIF transfers.

Curiously enough, writing to it does seem to trigger a WR4B serial packet to PIF, so it can actually
be used to transfer a word, with the following sequence:

* First, we need to populate the internal SI register that holds the "current address" to PIF. To do so, we can simply trigger a read from PIF_RAM at the desired location. The read will be executed, and the internal SI register will hold that address.
* Now, write a 32-bit word of data to `SI_PIF_AD_WR4B`. This goes into the internal "current data" register of SI, and triggers a WR4B transfer using the "current address" (loaded with the previous trick) and the "current data", effectively writing the word to PIF RAM.

The sequence triggers a non-blocking write, but also direct writes to the memory mapped area of PIF_RAM are non-blocking, so there does not seem to be any reason of using this register.

After writing to this register, the DMA_BUSY bit in SI_STATUS goes to 1 for a small amount of time, even though no actual DMA transfer is executed.


==== <span style="display:none;">0x0480 0010 - SI_PIF_AD_WR64B ====
----
{{#invoke:Register table|head|550px|SI_PIF_AD_WR64B <code>0x0480 0010</code>}}
{{#invoke:Register table|foot}}
'''TODO'''
==== <span style="display:none;">0x0480 0014 - SI_PIF_AD_RD4B ====
----
{{#invoke:Register table|head|550px|SI_PIF_AD_RD4B <code>0x0480 0014</code>}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[31:24]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | DATA[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-0 | DATA | 32-bit data to be transferred to PIF-RAM
}}

This register is very similar to SI_PIF_AD_WR4B: it also is directly mapped to the internal "current data" word for PIF transfers, but writing to it triggers a RD4B serial packet to PIF. So a read is actually executed and the data is fetched into "current data" and is thus available for reading later. No DMA is performed though.

Using a trick similar to that described in SI_PIF_AD_WR4B, it is possible to actually triggers a memory read from a selected location, but it is superfluous since it is sufficient to access the memory mapped PIF-RAM to do the same.

After writing to this register, the DMA_BUSY bit in SI_STATUS goes to 1 for a small amount of time, even though no actual DMA transfer is executed.

==== <span style="display:none;">0x0480 0018 - SI_STATUS ====
----
{{#invoke:Register table|head|950px|SI_STATUS <code>0x0480 0018</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || R-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || INTERRUPT || colspan="4" | DMA_STATE[3:0]
{{#invoke:Register table|row|7:0}}
| U-0 || U-0 || U-0 || U-0 || R-0 || R-0 || R-0 || R-0
|-
| colspan="4" | PCH_STATE[3:0] || style="font-size: 88%;" | DMA_ERROR || style="font-size: 88%;" | READ_PENDING || IO_BUSY || DMA_BUSY
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-13 | Undefined | Initialized to <code>0</code>
| 12 | INTERRUPT | Copy of SI interrupt flag from [[MIPS Interface#0x0430_0008_-_MI_INTERRUPT|MIPS Interface]], <br>{{spaces|4}}Writing any value to SI_STATUS acknowledges the interrupt.  <br>{{spaces|4}}SI interrupts occur when a DMA or a direct write finishes.
| 11-8 | DMA_STATE[3:0] | Internal DMA state. Non-zero values indicate activity.
| 7-4 | PCH_STATE[3:0] | Internal PIF channel state. Non-zero values indicate activity.
| 3 | DMA_ERROR | Set when overlapping DMA requests occur, or when writing to a misaligned address. Can only be cleared with a power reset.
| 2 | READ_PENDING | Unknown?
| 1 | IO_BUSY | Set when a direct memory write to PIF_RAM is in progress.
| 0 | DMA_BUSY | Set when a read or write DMA, or an IO write, is in progress.
}}

== iQue Player ==

On the iQue Player, the Serial Interface was substantially reworked as the PIF-NUS was removed from the design; the DMA engine no longer transfers data to/from the PIF over a serial line. DMA writes from SDRAM to the SI simply acquires 32 bytes of data from SDRAM, processing of this data is deferred until DMA reads from the SI back to SDRAM similarly to N64. When a DMA read back to SDRAM is requested, the data supplied by the DMA write is processed and a response is fetched from joybus devices.

The format of the data is stricter than on N64 and only properly supports small commands. Each joybus channel is allotted 8 bytes (effectively 7) in the data:
 - The first byte of the first channel must be sent as 0xFF, otherwise the result will be meaningless (a buffer full of 0xFF). The first byte of the other channels is ignored and skipped over.
 - The second byte is the TX length as on N64, the lower 6 bits determine how many bytes the joybus device receives while bit 7 may behave the same as on n64, skipping the device. If the number of bytes to send is 0 the device receives nothing.
 - The third byte is the RX length as on N64, the lower 3 (TOVERIFY) bits determine how many bytes it should expect to receive from the joybus device.
 - The remaining 5 bytes contain data that may be sent to the joybus device. If the TX length is greater than 5, the last byte is repeated out to the device to fill the rest of the packet.

When the data is DMA'd back to RAM, each channel contains:
 - The first byte is always 0xFF, irrespective of what was there when the data was uploaded.
 - The second byte is the lower 6 bits of the input TX length.
 - The third byte is the lower 3 bits of the input RX length and bits 6 & 7 are error bits like on N64.
 - The fourth byte is always the fourth byte from the input data.
 - The remaining 4 bytes contain RX data received from the joybus device. If the amount of data received was less than 4 bytes, the remaining bytes are the same as the input data.

Unlike on N64, it is not possible to upload a block of data to the SI and use it multiple times. It is also not necessary to set any bits in byte 63, since the DMA is just 32 bytes.
