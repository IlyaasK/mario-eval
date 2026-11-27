<!--
  Source: https://n64brew.dev/wiki/Memory_map
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The Memory Management Unit (MMU) in the CPU utilizes a large virtual memory space to map to various physical addresses in different ways. All memory accesses made by the CPU, whether instruction fetches or load/store instructions, use virtual addresses. The MMU uses five virtual memory segments to decide how the addresses will be mapped to the physical memory space.

Internally, all addresses are 64-bits wide. However, when in 32-bit addressing mode, the upper 32 bits are sign-extended. 
== Virtual Memory Map ==
The is the 32-bit virtual address space (used by most games and homebrew toolchains):
{| class="wikitable"
! colspan=2 | Address Range !! Name !! Description
|-
| 0x00000000 || 0x7FFFFFFF || KUSEG || User segment, TLB mapped
|-
| 0x80000000 || 0x9FFFFFFF || KSEG0 || Kernel segment 0, directly mapped, cached
|-
| 0xA0000000 || 0xBFFFFFFF || KSEG1 || Kernel segment 1, directly mapped, uncached
|-
| 0xC0000000 || 0xDFFFFFFF || KSSEG || Kernel supervisor segment, TLB mapped
|-
| 0xE0000000 || 0xFFFFFFFF || KSEG3 || Kernel segment 3, TLB mapped
|}
For the directly mapped segments KSEG0 and KSEG1, addresses are directly translated to physical addresses by subtracting by the base address of the respective segment. Thus they can only map to the physical address range <code>0x00000000 - 0x1FFFFFFF</code>.

Refer to the [[Translation lookaside buffer]] article and the [[TLB mapping|TLB mapping usage guide]] for more information about TLB mapped segments.

== Physical Memory Map ==
{| class="wikitable"
!style="width: 10%"|Bus / Device
! colspan=2 | Address Range 
!Mirror mask!! style="width: 15%" | Name !! Description
|-
| rowspan="3" |RDRAM
| 0x00000000 || 0x03EFFFFF 
|0x00000000|| [[RDRAM]] memory-space || RDRAM memory. See [[RDRAM_Interface#Memory_addressing]] and [[RDRAM#RDRAM_addressing]] for details about their mapping.
|-
| 0x03F00000 || 0x03F7FFFF 
|0x00000000|| [[RDRAM#Registers|RDRAM Registers]] || RDRAM registers. See [[RDRAM_Interface#Memory_addressing]] and [[RDRAM#RDRAM_addressing]] for details about their mapping.
|-
| 0x03F80000 || 0x03FFFFFF 
|0x00000000|| [[RDRAM#Registers|RDRAM Registers]] (broadcast) || Write-only. All connected RDRAM will act on this register write request. See [[RDRAM_Interface#Memory_addressing]] and [[RDRAM#RDRAM_addressing]] for details.
|-
| rowspan="13" |RCP
| 0x04000000 || 0x04000FFF 
|0x0003E000|| [[Reality Signal Processor/Interface#DMEM and IMEM|RSP DMEM]]|| RSP Data Memory
|-
| 0x04001000 || 0x04001FFF 
|0x0003E000|| [[Reality Signal Processor/Interface#DMEM and IMEM|RSP IMEM]]|| RSP Instruction Memory
|-
| 0x04040000 || 0x040BFFFF 
|0x0007FFE0|| [[RSP|RSP Registers]] || RSP DMAs, status, semaphore, program counter, IMEM BIST status
|-
|0x040C0000
|0x040FFFFF
|0x00000000
|Unmapped
|This area is completely ignored by the RCP. Any access in this area will freeze the CPU as the RCP will ignore the read/write and the CPU will never receive a reply.
|-
| 0x04100000 || 0x041FFFFF 
|0x001FFFE0|| [[Reality Display Processor|RDP Command Registers]]|| RDP DMAs, clock counters for: clock, buffer busy, pipe busy, and TMEM load
|-
| 0x04200000 || 0x042FFFFF 
|?|| RDP Span Registers || TMEM BIST status, DP Span testing mode
|-
| 0x04300000 || 0x043FFFFF 
|0x001FFFF0|| [[MIPS Interface]] (MI) || Init mode, ebus test mode, RDRAM register mode, hardware version, interrupt status, interrupt masks
|-
| 0x04400000 || 0x044FFFFF 
|0x001FFFC0|| [[Video Interface]] (VI) || Video control registers
|-
| 0x04500000 || 0x045FFFFF 
|0x001FFFE0|| [[Audio Interface]] (AI) || Audio DMAs, Audio DAC clock divider
|-
| 0x04600000 || 0x046FFFFF 
|0x001FFFC0|| [[Peripheral Interface]] (PI) || Cartridge port DMAs, status, Domain 1 and 2 speed/latency/page-size controls
|-
| 0x04700000 || 0x047FFFFF 
|0x001FFFE0|| [[RDRAM Interface]] (RI) || Operating mode, current load, refresh/select config, latency, error and bank status
|-
| 0x04800000 || 0x048FFFFF 
|0x001FFFC0|| [[Serial Interface]] (SI) || SI DMAs, PIF status
|-
| 0x04900000 || 0x04FFFFFF 
|0x00000000|| Unmapped || This area is completely ignored by the RCP. Any access in this area will freeze the CPU as the RCP will ignore the read/write and the CPU will never receive a reply.
|-
| rowspan="4" |PI external bus
| 0x05000000 || 0x05FFFFFF 
|?|| N64DD Registers || Contains the N64DD I/O registers.
Accesses here are forwarded to the [[PI|PI bus]], with the same address within the PI address space, using the "Domain 1" configuration set. 
When not present, this is a [[Peripheral Interface#Open bus behavior|PI open bus]] area. 
|-
| 0x06000000 || 0x07FFFFFF 
|?|| N64DD IPL ROM || Contains the N64DD ROM used during boot, sometimes called IPL4. This is executed whenever the console is turned on with a N64DD connected, in place of the [[PIF-NUS#Console startup|IPL3]].
Accesses here are forwarded to the [[PI|PI bus]], with the same address within the PI address space, using the "Domain 1" configuration set. 
When not present, this is a [[Peripheral Interface#Open bus behavior|PI open bus]] area.
|-
| 0x08000000 || 0x0FFFFFFF 
|?|| Cartridge SRAM/FlashRAM || When the cartridge uses SRAM or [[Flash|FlashRAM]] for save games, this is conventionally exposed at this address range.
Accesses here are forwarded to the [[PI|PI bus]], with the same address within the PI address space, using the "Domain 2" configuration set.  This is one of the few address ranges which are in Domain 2, probably because it is common to access SRAM/FlashRAM with a different (slower) protocol.
When not present, this is a [[Peripheral Interface#Open bus behavior|PI open bus]] area.
|-
| 0x10000000 || 0x1FBFFFFF 
|0x00000000|| [[ROM Header|Cartridge ROM]]|| The cartridges expose the ROM at this address. Normally, games will load assets and overlays via PI DMA for speed concerns, but the ROM is nonetheless memory mapped. Notice that cache accesses are not allowed here (and in all PI external bus accesses, see below for details), so while it is possible to run code directly from ROM, it will be extremely slow as it would not leverage the instruction cache.
Accesses here are forwarded to the [[PI|PI bus]], with the same address within the PI address space, using the "Domain 1" configuration set. 
When not present (eg: when booting a disk-only N64DD game without a cartridge), this is a [[Peripheral Interface#Open bus behavior|PI open bus]] area.
|-
| rowspan="3" |SI external bus
| 0x1FC00000 || 0x1FC007BF 
|?|| PIF ROM ([[Initial Program Load|IPL1/2]]) || Executed on boot
|-
| 0x1FC007C0 || 0x1FC007FF 
|?|| [[PIF-NUS|PIF]] RAM || Controller and EEPROM communication, and during IPL1/2 is used to read startup data from the PIF
|-
| 0x1FC00800 || 0x1FCFFFFF 
|?|| Reserved || Unknown usage
|-
| rowspan="2" |PI external bus
| 0x1FD00000 || 0x1FFFFFFF 
|0x00000000|| Unused || Accesses here are forwarded to the [[PI|PI bus]], with the same address within the PI address space, using the "Domain 1" configuration set. 
No known PI device uses this range, so it will normally be a [[Peripheral Interface#Open bus behavior|PI open bus]] area.
|-
|0x20000000
|0x7FFFFFFF
|0x00000000
|Unused
|Accesses here are forwarded to the [[PI|PI bus]], with the same address within the PI address space, using the "Domain 1" configuration set. 
No known PI device uses this range, so it will normally be a [[Peripheral Interface#Open bus behavior|PI open bus]] area.

NOTE: this range can be accessed by CPU only via TLBs or via direct 64-bit addressing, using the directly mapped, uncached segment (virtual 64-bit address: <code>0x9000_0000_nnnn_nnnn</code>).
|-
|
| 0x80000000 || 0xFFFFFFFF 
|0x00000000|| Unmapped || This area is completely ignored by the RCP. Any access in this area will freeze the CPU as the RCP will ignore the read/write and the CPU will never receive a reply.
|}

== Physical Memory Map accesses ==
The physical memory map is implemented by RCP, as the VR4300 only talks directly to RCP. The bus between VR4300 and RCP is called [[SysAD Interface|SysAD]]. The RCP behaves differently with different access sizes depending on the specific area of the map and the subcomponent in charge of implementing it.

The SysAD bus is described at the hardware level in the [[SysAD Interface|SysAD page]], but to understand the effects on memory map it is sufficient to understand how data is marshalled for reads and writes. Since SysAD is a 32-bit bus, 32-bit accesses are the "native" ones, and the other access sizes are made in a weird way built upon a 32-bit data exchange.

* Reads: VR4300 puts the address on the bus and the size of the access (8, 16, 32, 64). The RCP typically returns a full (aligned) 32-bit word address (or two, in case of a 64-bit read), from which the VR4300 extracts the correct portion. For instance, when reading 8-bit from address <code>0x0000'0001</code>, the RCP will put on the bus the 32-bit values at <code>0x0000'0000 - 0x0000'0003</code>, and the VR4300 will then just isolate the requested 8 bits.
* Writes: VR4300 puts the address on the bus, the size of the access, and then the 32-bit value to be written. When the access is made using 8 or 16 bits, the value on the bus is prepared to match with the aligned 32-bit address. This is the same of what happens for reads, but this time it is the VR4300 that prepares the data. For instance, if register <code>S0=0x1234'5678</code>, <code>A0=0x0400'0001</code> and the opcode <code>SB S0, 0(A0)</code> is run, the VR4300 puts on the bus the value <code>S0 << 8</code>, that is <code>0x3456'7800</code>. RCP ignores the lower 2 bits of the address and the '''access size''', so any RCP register or Mapped memory will treat it as 32bit write of <code>0x3456'7800</code> to <code>Address & 0xfffffffc</code>, So even if it's an 8 bit write opcode, the upper bits of register <code>S0</code> leak onto the bus. However, the lower bits of '''address''' and '''access size''' are passed on to the RDRAM devices (see below). 

Notice that misaligned address are forbidden by MIPS architecture and they will result in an Address Exception. So all accesses that go through the memory map are always aligned to the access size (eg: aligned to 2 bytes for 16-bit reads/writes).

=== Range 0x0000'0000 - 0x03EF'FFFF (RDRAM memory) ===
The accesses in this area are handled by RCP via RI (Ram Interface). When the VR4300 reads or writes a location in this range, it gets stalled while the RI communicates with the RDRAM via the RAMBUS serial protocol. As soon as the read or write is finished, the VR4300 is released. Effectively, all reads and writes are synchronous (blocking) from the point of view of the VR4300, as you would expect when accessing a RAM. All access sizes work correctly: 8-bit, 16-bit, 32-bit, 64-bit. Support smaller access sizes is implemented the RDRAM device, which uses the lower bits of '''address''' and '''access size''' passed from RCP to generate a byte mask. 

The RDRAM area is the only areas in the memory map where the RCP supports '''cached''' accesses. This allows the VR4300 to issue the cache fills/flushes at the SysAD level to leverage the internal data and instruction cache (either via the KSEG0 directly-mapped segment, or through a TLB configured with the cache setting). Instead cache requests are ignored for all the other address ranges, and they will thus freeze the CPU requiring a hard reset.


=== Range 0x03F0'0000 - 0x03FF'FFFF (RDRAM registers) ===
The accesses in this area are handled by RCP via RI (Ram Interface). When the VR4300 reads or writes a location in this range, it gets stalled while the RI communicates with the RDRAM via the RAMBUS serial protocol. As soon as the read or write is finished, the VR4300 is released. Effectively, all reads and writes are synchronous (blocking) from the point of view of the VR4300, as you would expect when accessing a RAM.

=== Range 0x0400'0000 - 0x04FF'FFFF (RCP registers) ===
The accesses in this area are handled by RCP itself without going to an external bus, and are dispatched internally to the correct subsystem. Access to a register might optionally stall the VR4300 if the subsystem is designed to do so (eg: to perform a long blocking operation on write), but in general for standard registers, they are quite fast and take only 5-6 PClock cycles (MI regs are a bit faster and take about 2 cycles). 

Accesses in this area are affected by a simplified hardware implementation of the RCP SysAD bus, so '''''access size is ignored'''''. Only uncached accesses are allowed; cached accesses will be ignored by RCP causing a VR4300 freeze, requiring a hard reboot. This means that:

* Reads: RCP will ignore the requested access size and will just put the requested 32-bit word on the bus. Luckily, this is the correct behavior for 8-bit and 16-bit accesses (as explained above), so the VR4300 will be able to extract the correct portion. 64-bit reads instead will completely freeze the VR4300 (and thus the whole console), because it will stall waiting for the second word to appear on the bus that the RCP will never put.
* Writes: RCP will ignore the requested access size and just write the word that was put on the bus directly into the hardware register. For 8-bit and 16-bit accesses, this means that the shifted value prepared by the VR4300 is the one that will be written verbatim. Reprising the example above, if <code>S0=0x1234'5678</code>, <code>A0=0x0460'0011</code>, running <code>SB S0, 0(A0)</code> will write the value <code>0x5678'0000</code> to the RCP hardware register <code>0x0460'0010</code>. For 64-bit accesses, as they are written on the bus MSB-first, the RCP will write the MSB to the hardware register, ignoring the LSB.

=== Range 0x1FC0'0000 - 0x1FCF'FFFF (SI external bus) ===
NOTE: this section is very similar to the one about PI external bus. The two areas behave exactly the same wrt the interface between VR4300 and RCP, despite the access being forward to different buses.

All accesses made by the VR4300 in these ranges are forward externally by RCP on the external SI bus. This allows the CPU to access the onboard memory of the [[PIF-NUS]] device; normally this is the onboard RAM, but also ROM can be accessed during boot (it is then locked out for security reasons).

Accesses in this area are affected by the same simplified SysAD implementation described above, so '''access size is ignored.''' Only uncached accesses are allowed; cached accesses will be ignored by RCP causing a VR4300 freeze, requiring a hard reboot. The effect is the same described before.

Moreover, there is one important additional detail:

* All writes are performed '''asynchronously''' by the SI. Making a write in this area will in fact just cause the SI to latch the value internally, and release the VR4300 immediately. The write will then happen in background. The status of the ongoing write will be reflected by the SI "I/O busy" status bit, which will be set to 1 until the write is finalized. While a write is ongoing, further writes are ignored, and reads (from any address) are automatically delayed until the write is finished. For further information on this, please check the [[SI|SI page]]. Notice that the SI doesn't know that a certain range of addresses are mapped to ROM and thus read-only, so even writes in the ROM area follow this pattern; they are just ignored by the PIF itself.

=== Ranges 0x0500'0000 - 0x1FBF'FFFF and 0x1FD0'0000 - 0x7FFF'FFFF  (PI external bus) ===
NOTE: this section is very similar to the one about SI external bus. The two areas behave exactly the same wrt the interface between VR4300 and RCP, despite the access being forward to different buses.

All accesses made by the VR4300 in these ranges are forward externally by RCP on the external PI bus. This allows the CPU to access external devices connected to the parallel bus like the cartridge ROM, SRAM and FlashRAM.

Accesses in this area are affected by the same simplified SysAD implementation described above, so '''access size is ignored.''' Only uncached accesses are allowed; cached accesses will be ignored by RCP causing a VR4300 freeze, requiring a hard reboot. The effect is the same described before.

Moreover, there are two important additional details:

* All writes are performed '''asynchronously''' by the PI. Making a write in this area will in fact just cause the PI to latch the value internally, and release the VR4300 immediately. The write will then happen in background. The status of the ongoing write will be reflected by the PI "I/O busy" status bit, which will be set to 1 until the write is finalized. While a write is ongoing, further writes are ignored, and reads (from any address) return the 32-bit value that is being written. For further information on this, please check the [[Peripheral Interface|PI page]]. Notice that the PI doesn't know whether a certain device is read-only, so even writes in the ROM area follow this pattern; they are just ignored by the ROM itself.
* The external PI bus is 16-bit. Given that the RCP only knows of 32-bit accesses (as access size is ignored), this means that each read or write performed by the VR4300 will cause exactly two reads or two writes on the PI bus: first the MSB at the address specified by the CPU (ignoring bit 0, so that the address is aligned to 16 bit), then the LSB at address+2. This might seem a small implementation detail, but it does actually cause an important and visible bug. For instance, if the VR4300 requests a 16-bit read at address <code>0x1000'0002</code>, the RCP (that ignores access sizes) will do two 16-bit reads on the cartridge bus at <code>0x1000'0002</code> and <code>0x1000'0004</code>, and will put on the SysAD bus the 32-bit word at <code>0x1000'0002 - 0x1000'0005</code>. This is a violation of the SysAD protocol explained above: in fact, in reply to a 16-bit read at <code>0x1000'0002</code>, the RCP should have put on the bus the 32-bit word at <code>0x1000'0000 - 0x1000'0003</code> instead. Because of this, effectively a 16-bit read at <code>0x1000'0002</code> returns the 16-bit word at <code>0x1000'0004</code> instead.

=== Range 0x8000'0000 - 0xFFFF'FFFF (Unmapped) ===
This range is not handled by RCP. All writes are ignored, and reads lock up the VR4300 because the RCP is stalled and does not return any data on the bus.

In official documentation this region of the physical memory map is named "External SysAD Device". The designers appear to have intentionally neglected to have the RCP generate a response to this address range to allow an alternate responder on the SysAD bus handle the request instead. On a retail N64 there are no alternate responders, the SysAD bus exclusively connects the VR4300 and the RCP so in all cases an access to this region does nothing interesting, but this may not be the case on other devices such as the Indy dev board or the Aleck64. Examples of alternate responders / external SysAD devices for these are the RDB debug interface on the Indy dev board and additional (CPU access only) SDRAM on the Aleck64.
