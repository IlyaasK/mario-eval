<!--
  Source: https://n64brew.dev/wiki/Parallel_Interface
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The Parallel Interface (commonly referred to as the '''PI''', or Peripheral Interface) is one of multiple I/O interfaces in the RCP, which is used to communicate with [[Game Pak|game cartridges]] or other devices connected to either the cartridge port or expansion port on the bottom of the console. (e.g. 64DD) The PI is not to be confused with the [[PIF-NUS|PIF]] (or PIF-NUS) which is an entirely separate IC.

Memory mapped registers are used to configure the Parallel Interface and initiate DMA reads and writes. The base address for these registers is <code>0x0460 0000</code>, also known as PI_BASE. However, because all memory accesses in the CPU are made using virtual addresses, the following addresses must be offset appropriately. For non-cached reads/writes, add <code>0xA000 0000</code> to the address. As an example, to directly write to the PI_DRAM_ADDR register, use address <code>0xA460 0000</code>.


= The PI Bus =
The PI bus is the bus where external devices can be connected, via either the cartridge port on the top of the console, or the expansion port at the bottom of the console. Notice both ports are electrically connected to the same bus, even if the connector is different.

The bus address is 32-bit and the values being transferred are 16-bits. So each access (read or write) is made to a 32-bit address with a 16-bit data. The PI (as master device) issues reads and writes to the bus with a wire protocol detailed below. Each device is expected to use an address range (a subset of the whole 32-bit address space); the device will receive all reads and writes requests from PI, and is expected to reply / execute those falling within the address range of interest. The PI has no way of knowing if one or more devices are attached to the bus, it does not know which address ranges are used by what device (there is no "address registration / reservation system"), and there is no handling of conflicts.

The PI will issue reads or writes as drive by the CPU via two different systems:

* DMA: this allows to transfer multiple words. In general, the PI bus protocol allows the PI to write the address once, and then either reads or writes multiple consecutive words, and the DMA will use this mechanism to do quicker transfers. In fact, addresses in the PI bus are virtually split in "pages" of configurable size. The PI is allowed to read/write multiple words within the same page, so during the DMA will issue the address only once for page, and then read/write multiple words as requested. This is done to speed up transfers (as issuing a new address after every word would waste time).
* Direct I/O: part of the 32-bit PI address space is [[Memory map|memory mapped]] to the CPU address space. This means that when the CPU accesses one of these memory mapped addresses, the PI will perform a read or write on the bus. The mapped addresses are only those in the range  <code>0x0500_0000 -  0x1FBF_FFFF</code> and  <code>0x1FD0_0000 -  0x7FFF_FFFF</code>. Addresses outside of these ranges can only be accessed via DMA. Notice also that direct I/O accesses can only be done as 32-bit words (concatenating two consecutive 16-bit reads), see [[Memory map#Ranges 0x0500'0000 - 0x1FBF'FFFF and 0x1FD0'0000 - 0x7FFF'FFFF (PI external bus)]] for more information.

'''NOTE:''' it is easy to get confused with the different kind of addresses. Addresses mentioned here are '''PI bus addresses''', which is a 32-bit namespace by itself. Addresses in the CPU physical memory map are a different namespace. They can be confused because of the memory mapped addresses: accessing physical address '''0x0700_0000 in the CPU''' does map exactly to '''PI address 0x0700_0000''', but in general the two namespaces are technically separated. For instance, '''PI address 0x0000_1234''' is a valid PI address on the bus where a device could be attached, but reading from physical address '''0x0000_1234 on the CPU''' accesses RDRAM instead; in fact PI address 0x0000_1234 is not memory mapped, so the only way to access it is via DMA.

=== Domains ===
To cope with different peripherals, the PI allows to configure some parameters that affect the bus protocol:

* '''PGS (page size).''' This is the size of a virtual page, and defines how often the PI must issue a new address during a DMA transfer. For instance, if the configure page size is 32 16-bit words, assuming an aligned transfer, the PI will issue an address at the start, and then read (or write) 32 consecutive words.
* '''LAT (latency).''' Number of RCP clock cycles to wait between the address and the transfer of the first word
* '''PWD'''
* '''RLS'''

The PI stores two set of configurations for these 4 registers, and uses them for different ranges of the address space. These two sets are called "domain 1" and "domain 2". Most of the address space is accessed using the "domain 1" configuration, but a few ranges are accessed as "domain 2". See this table for the mapping:
{| class="wikitable"
|+
!PI address range
!Domain
!Device
|-
|0x0000_0000 - 0x04FF_FFFF
|Domain 1
|No known device exists that operates in this range 
|-
|0x0500_0000 - 0x05FF_FFFF
|Domain 2
|64DD registers
|-
|0x0600_0000 - 0x07FF_FFFF
|Domain 1
|64DD ROM
|-
|0x0800_0000 - 0x0FFF_FFFF
|Domain 2
|SRAM
|-
|0x1000_0000 - 0xFFFF_FFFF
|Domain 1
|ROM (though this address range is huge, and ROM only typically occupied a small portion of it)
|}
There is no way to have more than two domains, nor to decide which domain is used for some specific address. The above table is hardcoded in the PI itself, and cannot the changed. In general, software that needs to change domain parameters before accessing a device is advised to do that in a transactional way, so that the default values are restored after the access for other peripherals.

=== Open bus behavior ===
Writes made to addresses with no "receiver" devices cause no harm; the writes are just ignored. As explained above, the PI has absolutely no notion if devices are attached or not (and whether they care about some addresses) so all writes will always be performed as if somebody cared about them. In particular, notice also that PI will also execute writes to the ROM address space (as it has no notion that the ROM is read-only, nor that a ROM is mapped to those addresses!): the cartridge will then ignore those writes.

Reads made to addresses with no "receiver" devices cause an open-bus behavior: the 32-bit word returned by PI is the 16-bit lowest part of the address put on the bus, repeated in both halves. For instance, a direct I/O 32-bit read from PI address <code>0x6666_DCBA</code> will return the value <code>0xDCBA_DCBA</code>. When reading unmapped areas via DMA, the rule is the same but the address returned is the address of the page being accessed (the only one physically put on the bus), and it is repeated for all words read until page change.

= Registers =
'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at power on
[x:y] = Specifies bits x to y, inclusively</pre>
==== <span style="display:none;">0x0460 0000 - PI_DRAM_ADDR ====
----
{{#invoke:Register table|head|550px|PI_DRAM_ADDR <code>0x0460 0000</code>}}
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
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || R-0
|-
| colspan="7" | DRAM_ADDR[7:1] || 0
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-24 | Undefined | Initialized to <code>0</code>
| 23-1 | DRAM_ADDR[23:1] | Base address of RDRAM for PI DMAs; notice that bit 0 cannot be written and is fixed to zero.
}}
'''Extra Details:'''
: Note that DMA transfers are buggy if DRAM_ADDR[2:0] are not all zero, see [[#Unaligned DMA transfer|below]].

==== <span style="display:none;">0x0460 0004 - PI_CART_ADDR ====
----
{{#invoke:Register table|head|550px|PI_CART_ADDR <code>0x0460 0004</code>}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | CART_ADDR[31:24]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | CART_ADDR[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | CART_ADDR[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || R-0
|-
| colspan="7" | CART_ADDR[7:1] || 0
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-1 | CART_ADDR[31:1] | Base address of the PI bus (e.g. cartridge) for PI DMAs; notice that bit 0 cannot be written and is fixed to 0.
}}

'''Extra Details:'''
: This register is automatically updated by PI after any PI transfer (both DMA and direct I/O). In both cases, it will contain the first address ''after'' the last transferred word. DMA transfers are a bit complex in this regard, so see below in this page where the mechanics of the transfers are detailed.

==== <span style="display:none;">0x0460 0008 - PI_RD_LEN ====
----
{{#invoke:Register table|head|550px|PI_RD_LEN <code>0x0460 0008</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | RD_LEN[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | RD_LEN[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | RD_LEN[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-24 | Undefined | Initialized to <code>0</code>
| 23-0 | RD_LEN[23:0] | Number of bytes, minus one, to be transferred from RDRAM, to the PI bus
}}
'''Extra Details:'''
: Writing to this register will start the DMA transfer. Reading appears to always return `0x7F` (more research required).

==== <span style="display:none;">0x0460 000C - PI_WR_LEN ====
----
{{#invoke:Register table|head|550px|PI_WR_LEN <code>0x0460 000C</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | WR_LEN[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | WR_LEN[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | WR_LEN[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-24 | Undefined | Initialized to <code>0</code>
| 23-0 | WR_LEN[23:0] | Number of bytes, minus one, to be transferred from the PI bus, into RDRAM
}}
'''Extra Details:'''
: Writing to this register will start the DMA transfer. Reading appears to almost always return `0x7F` (see [[Peripheral Interface#PI WR LEN readbacks after a transfer|below]] for exceptions).

==== <span style="display:none;">0x0460 0010 - PI_STATUS ====
----
{{#invoke:Register table|head|550px|PI_STATUS <code>0x0460 0010</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-0 || U-0 || U-0 || U-0 || R-0 || R-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4"|Details below
{{#invoke:Register table|foot}}
<pre>
READ:                                 WRITE:
    [3]    Interrupt (DMA completed)      [3]    -
    [2]    DMA error                      [2]    -
    [1]    I/O busy                       [1]    Clear Interrupt
    [0]    DMA is busy                    [0]    Reset DMA controller and stop any transfer being done
</pre>

==== <span style="display:none;">0x0460 00n4 - PI_BSD_DOMn_LAT ====
----
{{#invoke:Register table|head|550px|PI_BSD_DOM1_LAT <code>0x0460 0014</code><br>
PI_BSD_DOM2_LAT <code>0x0460 0024</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | LAT[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-8 | Undefined | Initialized to <code>0</code>
| 7-0 | LAT[7:0] | The "LATch" value is the number of RCP cycles, minus one, after the address has been sent (falling edge of ALE_L) and before the first read or write may start (falling edge of /RD or /WR)
}}
'''Extra Details:'''
: During [[Initial_Program_Load#IPL2|IPL2]], the N64 will initialize Domain 1's LAT using data read from the cartridge [[ROM_Header|ROM header]]. All official ROMs set LAT = 64 (meaning (64+1)*16 = 1040ns).

==== <span style="display:none;">0x0460 00n8 - PI_BSD_DOMn_PWD ====
----
{{#invoke:Register table|head|550px|PI_BSD_DOM1_PWD <code>0x0460 0018</code><br>
PI_BSD_DOM2_PWD <code>0x0460 0028</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | PWD[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-8 | Undefined | Initialized to <code>0</code>
| 7-0 | PWD[7:0] | The "Pulse WiDth" value is the number of RCP cycles, minus one, the /RD or /WR signals are held low
}}
'''Extra Details:'''
: During [[Initial_Program_Load#IPL2|IPL2]], the N64 will initialize Domain 1's PWD using data read from the cartridge [[ROM_Header|ROM header]]. All official ROMs set PWD = 18 (meaning (18+1)*16 = 304ns).

==== <span style="display:none;">0x0460 00nC - PI_BSD_DOMn_PGS ====
----
{{#invoke:Register table|head|550px|PI_BSD_DOM1_PGS <code>0x0460 001C</code><br>
PI_BSD_DOM2_PGS <code>0x0460 002C</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | PGS[3:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-4 | Undefined | Initialized to <code>0</code>
| 3-0 | PGS[3:0] | The "PaGe Size" value configures how many bytes can be sequentially read/written on the bus before sending the next base address (Size {{=}} 2^(PGS+2) bytes)
}}
'''Extra Details:'''
: During [[Initial_Program_Load#IPL2|IPL2]], the N64 will initialize Domain 1's PGS using data read from the cartridge [[ROM_Header|ROM header]]. All official ROMs set PGS = 7 (meaning 2^(7+2) = 512 bytes).
: The smallest possible value, 0, means 2^(0+2) = 4 bytes; the largest means 2^(15+2) = 128KiB.

Page Size only matters for DMA transfers; all direct accesses via the PI are only ever 32 bits wide.

Notice that Page Size refers to aligned pages. For instance, with the default setting of 512 bytes, the PI will never allow a single burst to cross a 512 byte boundary. For instance, requesting 16 bytes from address 508 will actually generate two different burst transfers on the PI bus: the first of 4 bytes from offset 508, and the second of 12 bytes from offset 512.

==== <span style="display:none;">0x0460 00n0 - PI_BSD_DOMn_RLS ====
----
{{#invoke:Register table|head|550px|PI_BSD_DOM1_RLS <code>0x0460 0020</code><br>
PI_BSD_DOM2_RLS <code>0x0460 0030</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || colspan="2" | RLS[1:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-2 | Undefined | Initialized to <code>0</code>
| 1-0 | RLS[1:0] | The "ReLeaSe" value is the number of RCP cycles, minus one, that the /RD or /WR signals are held high between each 16-bits of data
}}
'''Extra Details:'''
: During [[Initial_Program_Load#IPL2|IPL2]], the N64 will initialize Domain 1's RLS using data read from the cartridge [[ROM_Header|ROM header]]. All official ROMs set RLS = 3 (meaning (3+1)*16 = 64ns).


= iQue Player-specific registers =

'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at power on
[x:y] = Specifies bits x to y, inclusively</pre>

==== <span style="display:none;">0x0460 0040 - PI_BB_ATB_UPPER</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_ATB_UPPER <code>0x0460 0040</code> (Read)}}
{{#invoke:Register table|row|31:24}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || IV Source
{{#invoke:Register table|row|7:0}}
| U-? || U-? || U-? || U-? || colspan="4"| U-?
|-
| — || — || CpuEn || DmaEn || colspan="4"| log2(Num Blocks)
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 8 | IV Source | Where to source the Initialization Vector from for AES decryption. See below.
| 5 | CpuEn | If set to 1, the mapping will be enabled for CPU reads
| 4 | DmaEn | If set to 1, the mapping will be enabled for DMA reads
| 3-0 | log2(Num Blocks) | log2 of the number of contiguous NAND blocks to map. This is applied to an ATB entry when '''ATB_LOWER''' registers are written.
}}

'''Extra Details'''
: This register supplies only half of the configuration for an ATB entry, also see the '''PI_BB_ATB_LOWER''' array of registers where PI addresses and the starting NAND block number are specified.
: Mappings work with sequences of blocks, whose length is a power of two. The register here contains the logarithm of the length so for instance writing "0" causes 1 block to be mapped; writing 4 causes 16 consecutive blocks to be mapped.
: ATB is the N64 PI address space emulator that translates PI DMAs into NAND flash accesses. Data stored on the NAND is encrypted with AES, ATB must transparently decrypt the data when a PI DMA requests it. To decrypt AES at an 0x10-aligned position '''P''' the data at '''P-0x10''' is also required, or if '''P=0''' then the Initialization Vector (IV) is required. At the start of a DMA, ATB will try to find the entry that maps the PI address for '''P-0x10''' into the NAND to fetch the needed prior data; for all cases but '''P=0''' this should resolve correctly with a contiguous PI address space mapping. To handle the '''P=0''' case an additional dummy mapping must precede the base address of the desired mapping, with the IV Source bit set to 1. When the IV Source bit is 1 the IV will be pulled from the memory at '''0x046104D0''' rather than reading any data off the NAND. For example if the mapping begins at PI address 0x10000000 as for Cartridge ROM, a dummy mapping for PI address 0x0FFFC000 with IV Source set to 1 should be programmed.

==== <span style="display:none;">0x0460 0048 - PI_BB_NAND_CTRL</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_NAND_CTRL <code>0x0460 0048</code> (Read)}}
{{#invoke:Register table|row|31:24}}
| R-0 || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| Busy || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-? || U-? || U-? || U-? || R-0 || R-0 || U-? || U-?
|-
| — || — || — || — || Single-bit Error || Double-bit Error || — || —
{{#invoke:Register table|row|7:0}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31 | Busy | Indicates that a command is currently executing.
| 11 | Single-bit Error | Indicates that a single-bit error was detected by ECC. These are automatically corrected so generally no action is required.
| 10 | Double-bit Error | Indicates that a double-bit error was detected by ECC. Unlike single-bit errors, these are not automatically recoverable.
}}

{{#invoke:Register table|head|800px|PI_BB_NAND_CTRL <code>0x0460 0048</code> (Write)}}
{{#invoke:Register table|row|31:24}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| Execute || Interrupt || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| colspan="8"| W-0
|-
| colspan="8"| NAND Command
{{#invoke:Register table|row|15:8}}
| W-0 || W-0 || colspan="2"| W-0 || W-0 || W-0 || colspan="2" | W-0
|-
| — || Buffer Select || colspan="2"| Device Select || Do ECC || Multicycle || colspan="2"| Data Length [9:8]
{{#invoke:Register table|row|7:0}}
| colspan="8"| W-0
|-
| colspan="8"| Data Length [7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31 | Execute | Setting this bit when writing will cause the last written command to begin execution.
| 30 | Interrupt | Whether the FLASH interrupt should be raised when the command finishes execution.
| 29 | ? | Unknown. Set when issuing Page Program (first cycle)
| 28 | ? | Unknown. Set when issuing Read 1, Read Status and Read ID
| 27 | ? | Unknown. Set when issuing Read 1, Block Erase (first cycle) and Page Program (first cycle)
| 26 | ? | Unknown. Set when issuing Read 1, Block Erase (first cycle) and Page Program (first cycle)
| 25 | ? | Unknown. Set when issuing Read 1, Block Erase (first cycle) and Page Program (first cycle)
| 24 | ? | Unknown. Set when issuing Read 1, Read ID and Page Program (first cycle)
| 23-16 | NAND Command | NAND Command to execute. Corresponds directly to commands for the K9F1208U0M flash.
| 15 | ? | Unknown. Set when issuing Read 1, Block Erase (second cycle) and Page Program (second cycle)
| 14 | Buffer Select | Selects which half of the 0x400-byte PI Buffer mapped at 0x04610000 should be used for DMA operations. See '''iQue Player-specific Memory''' for details on this buffer
| 13-12 | Device Select | Corresponds to Chip Enable signals on the card connector. Typically 0.
| 11 | Do ECC | Whether to do ECC
| 10 | Multicycle | Set to 1 if the command issued was not the last command in a multi-cycle sequence.
| 9-0 | Data Length | Data transfer length in bytes. Unlike most other lengths this is not length minus one, a length of 0 can be specified.
}}

'''Extra Details:'''
: Writing 0 to this register will clear any pending FLASH interrupt.

==== <span style="display:none;">0x0460 004C - PI_BB_NAND_CFG</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_NAND_CFG <code>0x0460 004C</code>}}
{{#invoke:Register table|row|31:24}}
| colspan="8"| U-?
|-
| colspan="8"| Configuration
{{#invoke:Register table|row|23:16}}
| colspan="8"| U-?
|-
| colspan="8"| Configuration
{{#invoke:Register table|row|15:8}}
| colspan="8"| U-?
|-
| colspan="8"| Configuration
{{#invoke:Register table|row|7:0}}
| colspan="8"| U-?
|-
| colspan="8"| Configuration
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-0 | Configuration | Likely specifies timing configurations for different NAND flash chips. It is currently unknown how to relate values programmed into this register and timing information found in datasheets.
}}

'''Extra Details'''

System software programs <code>0x753E3EFF</code> into this register to execute a Read ID command, then selects an appropriate configuration based on the ID:
{| class="wikitable"
! ID [31:16] !! NAND Size in Blocks !! NAND Size in MiB !! Configuration Value !! Part Number
|-
| 0xEC76 || 0x1000 || 64 || 0x441F1F3F || K9F1208U0M
|-
| 0xEC79 || 0x2000 || 128 || 0x441F1F3F || K9K1G08U0A or K9K1G08U0B
|-
| 0x9876 || 0x1000 || 64 || 0x753E1F3F || TC58512FT
|-
| 0x2076 || 0x1000 || 64 || 0x441F1F3F || NAND512W3A
|}

==== <span style="display:none;">0x0460 0058 - PI_BB_RD_LEN</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_RD_LEN <code>0x0460 0058</code>}}
{{#invoke:Register table|row|31:24}}
| colspan="8"| U-?
|-
| colspan="8"| —
{{#invoke:Register table|row|23:16}}
| colspan="8"| U-?
|-
| colspan="8"| —
{{#invoke:Register table|row|15:8}}
| colspan="7"| U-? || W-?
|-
| colspan="7"| — || Length [8]
{{#invoke:Register table|row|7:0}}
| colspan="8"| W-?
|-
| colspan="8"| Length [7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| ?-0 | Length | DMA Transfer Length (-1). Writes initiate a DMA from SDRAM starting at '''PI_DRAM_ADDR''' to the PI Buffer at '''0x04610000 + PI_CART_ADDR'''. Exact bit width unknown, it is at least long enough to transfer 0x200 bytes.
}}

'''Extra Details'''
: It is currently unknown what the behavior is if a DMA extends out of the bounds of the target PI Buffer, and whether both buffers can be accessed in one transfer. Spare buffers can't be accessed via DMA though.
: The busy bits in '''PI_STATUS''' also applies to these transfers.
: These transfers also trigger an interrupt upon completion. It is the same interrupt used for regular PI DMAs.

==== <span style="display:none;">0x0460 005C - PI_BB_WR_LEN</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_WR_LEN <code>0x0460 005C</code>}}
{{#invoke:Register table|row|31:24}}
| colspan="8"| U-?
|-
| colspan="8"| —
{{#invoke:Register table|row|23:16}}
| colspan="8"| U-?
|-
| colspan="8"| —
{{#invoke:Register table|row|15:8}}
| colspan="7"| U-? || W-?
|-
| colspan="7"| — || Length [8]
{{#invoke:Register table|row|7:0}}
| colspan="8"| W-?
|-
| colspan="8"| Length [7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| ?-0 | Length | DMA Transfer Length (-1). Writes initiate a DMA from the PI Buffer at '''0x04610000 + PI_CART_ADDR''' to SDRAM starting at '''PI_DRAM_ADDR'''. Exact bit width unknown, it is at least long enough to transfer 0x200 bytes.
}}

'''Extra Details'''
: It is currently unknown what the behavior is if a DMA extends out of the bounds of the target PI Buffer, and whether both buffers can be accessed in one transfer. Spare buffers can't be accessed via DMA though.
: The busy bits in '''PI_STATUS''' also applies to these transfers.
: These transfers also trigger an interrupt upon completion. It is the same interrupt used for regular PI DMAs.

==== <span style="display:none;">0x0460 0060 - PI_BB_GPIO</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_GPIO <code>0x0460 0060</code>}}
{{#invoke:Register table|row|31:24}}
| colspan="2"| R-? || U-? || U-? || U-? || colspan="2"| R-? || R-?
|-
| colspan="2"| Box ID [15:14] || — || — || — || colspan="2"| Box ID [10:9] || Box ID [8:6] [2]
{{#invoke:Register table|row|23:16}}
| colspan="2"| R-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| colspan="2"| Box ID [8:6] [1:0] || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| colspan="2"| RW-? || RW-? || RW-? || colspan="2"| RW-? || RW-? || RW-?
|-
| colspan="2"| RTC Output Enable || LED Output Enable || Power Output Enable || colspan="2"| RTC Control || LED Control || Power Control
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-16 | Box ID [15:0] | System software calls this area the "Box ID". Various sub-fields are read out of this area separately for varying purposes.
| 31-30 | Box ID [15:14] | System software reads this as some sort of model identifier. Precise meaning unknown. Whether all players have the same value here is unknown.
| 26-25 | Box ID [10:9] | System clock speed identifier? System software reads this to determine delay intervals for some operations.
| 24-22 | Box ID [8:6] | The Boot ROM checks this against bits [10:8] in a register at MI+0x10, if they don't match this value is copied there and the system is rebooted?
| 7-6 | RTC Output Enable | Output enables for the RTC bit lines. If off, the bit lines will be in high impedance and can be driven to logic low or logic high by the other end of the line. If on, the bit lines can be driven to logic low or logic high by writing 0 or 1 respectively to the RTC Control bits.
| 5 | LED Output Enable | Output enable for the LED bit line. If off, the bit line will be in high impedance and can be driven to logic low or logic high by the other end of the line. If on, the bit line can be driven to logic low or logic high by writing 0 or 1 respectively to the LED Control bit.
| 4 | Power Output Enable | Output enable for the Power bit line. If off, the bit line will be in high impedance and can be driven to logic low or logic high by the other end of the line. If on, the bit line can be driven to logic low or logic high by writing 0 or 1 respectively to the Power Control bit.
| 3-2 | RTC Control | RTC communication happens through these bits. The communication protocol is described in the [https://www.st.com/content/ccc/resource/technical/document/datasheet/19/24/95/e2/85/6a/47/30/CD00003139.pdf/files/CD00003139.pdf/jcr:content/translations/en.CD00003139.pdf ST M41T0 Serial RTC datasheet]; the lower bit is the clock line while the upper bit is the data line. When RTC Output Enable bits are 0 the RTC can drive the bus, in which case reading the RTC Control bits will read the values sent by the RTC.
| 1 | LED Control | If the LED Output Enable is 1, writing 0 or 1 to this bit will drive the LED bit line low or high. If 0, the LED on the front of the player will light up. If 1, the LED will switch off.
| 0 | Power Control | If the Power Output Enable is 1, writing 0 or 1 to this bit will drive the Power bit line low or high. If 1, the power will remain on. If 0, the device will power off.
}}

'''Extra Details:'''
: Whenever a GPIO control bit (with its corresponding output enable bit set) is set to 1, the corresponding bit line will be set to logic high (3.3v). If set to 0 (with output enable set) the bit line is set to logic low (0v).
: The LED lights up when the LED GPIO is 0 as the LED requires a voltage difference across it to light up. One side of the LED is fixed to 3.3v while the other side is connected to the LED GPIO port; when LED Control is 1 there is no voltage difference across the LED (3.3 - 3.3 = 0v) so it does not light up, while an LED Control of 0 creates a voltage difference (3.3 - 0 = 3.3v) so the LED lights up.

==== <span style="display:none;">0x0460 0070 - PI_BB_NAND_ADDR</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_NAND_ADDR <code>0x0460 0070</code>}}
{{#invoke:Register table|row|31:24}}
| colspan="5"| U-? || colspan="3"| W-?
|-
| colspan="5"| — || colspan="3"| Address [26:24]
{{#invoke:Register table|row|23:16}}
| colspan="8"| W-?
|-
| colspan="8"| Address [23:16]
{{#invoke:Register table|row|15:8}}
| colspan="8"| W-?
|-
| colspan="8"| Address [15:8]
{{#invoke:Register table|row|7:0}}
| colspan="8"| W-?
|-
| colspan="8"| Address [7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| ?-0 | Address | Set the NAND flash address that commands issued by '''PI_BB_NAND_CTRL''' will target. Exact bit width is unknown, however it is at least enough to address 128MiB (27 bits)
}}

'''Extra Details:'''
: To convert a page number to an address, multiply it by 512.
: To convert a block number to an address, multiply it by 0x4000.

==== <span style="display:none;">0x0461 0500 to 0x0461 0800 - PI_BB_ATB_LOWER</code> ====
----
{{#invoke:Register table|head|800px|PI_BB_ATB_LOWER <code>0x0461 0500 - 0x0461 0800</code>}}
{{#invoke:Register table|row|31:24}}
| colspan="8"| U-?
|-
| colspan="8"| NAND Block Number [15:8]
{{#invoke:Register table|row|23:16}}
| colspan="8"| U-?
|-
| colspan="8"| NAND Block Number [7:0]
{{#invoke:Register table|row|15:8}}
| colspan="8"| U-?
|-
| colspan="8"| PI Physical Address [29:14] [15:8]
{{#invoke:Register table|row|7:0}}
| colspan="8"| U-?
|-
| colspan="8"| PI Physical Address [29:14] [7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-16 | NAND Block Number | Starting block number to map to the provided PI address.
| 15-0 | PI Physical Address [29:14] | PI address to begin the mapping at, divided by 0x4000 the NAND block size.
}}

'''Extra Details'''
: There are 192 '''ATB_LOWER''' registers. Issuing a write to a particular register will program that ATB entry with a mapping, also using the current contents of '''ATB_UPPER''' to complete the entry configuration.
: The number of blocks to map comes from '''ATB_UPPER'''.
: Mappings involving non-contiguous or unsorted NAND blocks must occupy multiple ATB entries.
: These ATB entries should be sorted by PI address, from lowest to highest.
: It is not possible to write addresses that are not aligned to the NAND block size (0x4000)
: It is not possible to map more contiguous blocks than the PI address alignment allows in a single entry. For example it is not possible to map 2 contiguous blocks in the same ATB entry if the base address is 0x10004000. The maximum number of blocks you can map for given <code>(pi_addr, nblocks)</code> in a single ATB entry is <code>1 << min(ctz(pi_addr/0x4000), ceil(log2(nblocks)))</code> where <code>ctz(x)</code> counts the number of trailing zeros in the binary representation of <code>x</code>.

= iQue Player-specific memory =

In addition to extra registers, the iQue Player maps additional memory into the PI registers address space for use in various PI operations.
{| class="wikitable"
! colspan=2 | Address Range !! Name !! Description
|-
| 0x04610000 || 0x046101FF || PI Buffer 0 || Holds intermediate data between SDRAM and the NAND. NAND commands transfer data between this buffer and the flash; transfers between this buffer and SDRAM is done via DMAs triggered by '''PI_BB_RD_LEN''' and '''PI_BB_WR_LEN'''. AES decryptions happen in this buffer.
|-
| 0x04610200 || 0x046103FF || PI Buffer 1 || Same as Buffer 0 in operation.
|-
| 0x04610400 || 0x0461040F || PI Spare Data 0 || Holds "spare data" for buffer 0 contents.
|-
| 0x04610410 || 0x0461041F || PI Spare Data 1 || Holds "spare data" for buffer 1 contents.
|-
| 0x04610420 || 0x046104CF || AES Expanded Key || Holds the AES expanded key for AES decryption operations.
|-
| 0x046104D0 || 0x046104DF || AES Initialization Vector || Holds the AES IV for AES decryption operations.
|}

Access by the CPU to these buffers must be performed as if the buffers were memory mapped from PI address space: that is, it is important that the PI status register reports that the PI unit is idle before attempting a read or a write.
= Physical Bus Pinout =
The PI Bus is a Bi-directional and multiplexed interface with a 16bit data path to the ROM, 64DD, [[Flash]] Ram and cart RAM chips. It is used to send both the wanted address and data to and from the RCP. This is not to be confused with the serial EEPROM, CIC and RTC (real time clock) chips that go through the SI interface and PIF chip via the cartridge port as well.
{| class="wikitable"
|+
!Pin Name
!Cart pins
!Description
|-
|AD0
|28
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[16] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[0]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart. Bit [0]
|-
|AD1
|29
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[17] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[1]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [1]
|-
|AD2
|30
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[18] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[2]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [2]
|-
|AD3
|32
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[19] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[3]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [3]
|-
|AD4
|36
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[20] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[4]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [4]
|-
|AD5
|37
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[21] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[5]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [5]
|-
|AD6
|40
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[22] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[6]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [6]
|-
|AD7
|41
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[23] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[7]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [7]
|-
|AD8
|16
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[24] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[8]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [8]
|-
|AD9
|15
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[25] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[9]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [9]
|-
|AD10
|12
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[26] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[10]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [10]
|-
|AD11
|11
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[27] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[11]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [11]
|-
|AD12
|7
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[28] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[12]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [12]
|-
|AD13
|5
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[29] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[13]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [13]
|-
|AD14
|4
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[30] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[14]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [14]
|-
|AD15
|3
|This data bit is used with the following signals to represent the following
/ALEH - Signal changes from HIGH to LOW: Address Bit[31] is latched internally in the ROM

/ALEL - Signal changes from HIGH to LOW: Address Bit[15]  is latched internally in the ROM

/WR or /RD - Signal changes from LOW to HIGH: This will read/write to that ROM location latched in the Cart.  Bit [15]
|-
|/ALEH
|35
|Parts on the PI bus are expected to latch the high address (Bits[31:16]) when this goes from HIGH to LOW.

When this signal goes from LOW to HIGH it resets the internal address system so it can await for a new address request.

This stays HIGH when in idle and LOW when processing data. Commercial ROMs also use this as /CE, entering a low-power state while this signal is high.

This signal will be high for at least 7 FSB cycles, each time a new address is loaded.
|-
|/ALEL
|33
|Parts on the PI bus are expected to latch the low address (Bits[15:0]) when this goes from HIGH to LOW.
No action has been seen when this goes from LOW to HIGH.

This stays HIGH when in idle and LOW when processing data.

This signal will be high for at least 14 FSB cycles, each time a new address is loaded, ending 7 FSB cycles after ALEH falls.

|-
|/WR
|8
|This is the signal that sends a write command to the FLASH ram, SRAM or 64DD
While this signal is low, the RCP drives the PI bus with the current word of data.

When this signal goes from LOW to HIGH external parts are expected to record the value at that moment, if they need it. The RCP and external parts are also expected to increase the internal address counter in preparation for the next word transferred.

The RCP will not change this signal from HIGH to LOW until either the Latency (PI_BSD_DOMn_LAT) or Release (PI_BSD_DOMn_RLS) registers have counted the required number of FSB clocks.

This stays HIGH when idle.
|-
|/RD
|10
|This is the signal that sends a read command to the ROM, FLASH ram, SRAM or 64DD.
While this signal is low, the RCP expects that some device will drive the PI Bus.

When this signal goes from LOW to HIGH the RCP will record the value at that moment. The RCP and external parts are also expected to increase the internal address counter in preparation for the next word transferred.

The /RD signal has the same timing constraints as the /WR signal above.

This stays HIGH when idle.
|}

== PI Interface Process ==

=== Address output ===
[[File:Rom address output.png|Rom Address Output]]

===  Data Read ===
[[File:Rom Read Data.png|alt=Rom Read Data|Rom Read Data]]

=== Constant Read ===
[[File:Constant ROM Access.png|Constant ROM Access]]



= DMA Transfers =
PI DMA is well defined for so-called "aligned transfers", which are defined by the following constraints:

# RDRAM address must be 8 bytes aligned
# PI address must be 2 bytes aligned
# Length must be a multiple of 2

Notice that the second point might be considered redundant from a hardware point of view given that both registers holding addresses are fixed to be 2-byte aligned (LSB is fixed to 0), but from a software point of view, this has to be taken into account.

The behavior of PI DMA when the first and third constraint are not respected is not well designed; it seems like the designers attempted to implement support for loosing these constraints but gave up in the middle, leaving the hardware in a state that can only be described as "buggy". This also leaks some internal details on how the transfers are performed.

To implement PI DMA, the RCP uses an internal 128 byte buffer. The following section attempts to describe the exact process (though the *actual* process implemented in the hardware is unknown; the following does match in observable behavior).

NOTE: only DMA write transfers (PI -> RDRAM) have been analyzed in detail, using default PI DOM1 settings. It is expected that read transfers (RDRAM -> PI) behave in a similar way, though it's not been fully tested yet. We also expect PI DOM1 page size setting to somehow affect the transfer, though this has also not been explored yet.

==== Internal process ====
The transfer is split in blocks of maximum 128 bytes each one. Within each block, the PI first fills the internal buffer fetching data from the PI bus, and then write backs the buffer contents to RDRAM. This can be observed by monitoring PI_DRAM_ADDR and PI_CART_ADDR: during the transfer, it can be first seen PI_CART_ADDR moving forward, and then PI_DRAM_ADDR catching up with a leap (writing to RDRAM is much faster than reading PI).

In general for all blocks of the transfer (excluding the first one, see below), the logic appears to be as follows:

* Compute the block size. This is the smallest between the remaining length, the end of the current RDRAM page, and 128 bytes (which is the maximum size of the internal buffer). RDRAM pages are 2 KiB (0x800) long, so for instance if the current RDRAM address (at the beginning of the block) is 0x147e0, the block size will be 0x20 because the RDRAM page ends at 0x147ff.
* Fill the page using PI reads from the bus. All PI accesses are always 16-bit long, so if the block size was odd (which happens on the last block, if the remaining length is odd), one extra byte will be fetched from PI into the internal buffer.
* Write back into RDRAM. The exact format of RDRAM writes is unknown at the moment; since PI DMA transfers are well-defined for 8-byte aligned RDRAM addresses, it is assumed that 64-bit writes are used (a burst like that used for D/I cache writebacks would require 16-byte alignment or more to be performed). If an extra byte was fetched in the previous step, that byte is also written to RDRAM. So in general odd-length PI DMA transfers will transfer one byte more than requested.

The above logic applies for all blocks of the transfer, excluding the first one. The first block in fact is treated specially by PI. It appears that the goal of the designers was to use the first block to realign transfers to 8-byte in RDRAM, which possibly causes the first block to use smaller, masked writes to RDRAM. So, even if the RDRAM starting address is misaligned, all blocks besides the first one will begin from a 8-byte aligned RDRAM address, and behave with the logic described above.

==== Internal process: first block ====
These are the differences in logic while processing the first block, which mostly concerns how to handle the initial RDRAM misalignment. In this description, we refer to ''RDRAM misalignment'' as the amount of bytes that the RDRAM address is distant from the previous 8-byte aligned word (that is, the misalignment is the value of the last 3 bits of the RDRAM address). Notice that the RDRAM address hardware register has the LSB fixed 0, so misalignment can be either 2, 4, or 6.

* The internal 128 byte buffer is filled starting from the index matching the misalignment. This might affect the maximum size of the first block: for instance, if misalignment is 6, the maximum size is not 128 but 122, because the first 6 bytes are skipped.
* Writes to RDRAM seems to use some kind of masking, so they are correctly done at the byte granularity. This means that odd length transfers in the first block appear to work correctly. Notice that this applies only to the first block whatever its size is; the size (as described above) might be limited by the end of the RDRAM page, in which case only odd transfers up to there are working correctly.
* As an exception to the above exception, if the first block reaches the end of the 128 byte buffer, the last 2 bytes of the buffer are always written back in full to RDRAM, even though one less byte was requested.
** Example: PI DMA transfer with misalignment 0 and RDRAM page end far away. Odd lengths up to 125 (included) work correctly; odd transfers of exactly 127 bytes are rounded up to 128 (since they reach the last 16-bit word of the buffer). Also odd transfers of 129 or more, since they need two blocks to be performed, fall back into the general rule where one more byte is transferred.
** Example: PI DMA transfer with misalignment 6 and RDRAM page end far away. Odd lengths up to 119 (included) work correctly; odd transfers of exactly 121 bytes are rounded up to 122 (since they reach the last 16-bit word of the buffer). Also odd transfers of 123 or more, since they need two blocks to be performed, fall back into the general rule where one more byte is transferred.
* There seems to be a hardware bug related how RDRAM writes are performed, in case of misaligned addresses. It seems like the hardware is counting the block length starting from index 0 of the buffer, even though the first byte was actually placed at the index matching the misalignment, and even though masking is performed correctly. This means that for instance, if misalignment is 6 and the length of 8, the following happens:
** First, 8 bytes are fetched from the PI bus and put at index 6..13 in the internal buffer.
** Then, RDRAM writes are performed but the hardware believes the block ends at index 8, so only bytes 6..8 are written back to RDRAM.
* Symmetrically, if the buffer is full (128 bytes), the last 6 bytes will not be transferred because of the same bug (even if those bytes were fetched by the PI bus). So there will be a "hole" of 6 bytes in the RDRAM output buffer. For instance, if misalignment is 6 and the length is 1024, and the RDRAM page end is far away, the following happens on the first block:
** Block size is computed as 122 bytes.
** 122 bytes are fetched from the PI bus, and put at index 6..127 in the internal buffer.
** RDRAM writes are performed but the hardware believes that the block ends at index 121, so only bytes 6..121 are written back to RDRAM.
** Notice that, this notwithstanding, RDRAM address is correctly rounded up to 8 byte at the end of the block (see below), so the second block will behave correctly. There will be a hole in RDRAM as bytes 122.127 in the first block are never written back to RDRAM, so the content of RDRAM for those bytes is not affected by DMA.
* RDRAM address register is always rounded up to the next 8 byte alignment at the end of the first block. In most normal cases, the logic above already ensures that the address ends up being aligned at the end of the block, but the rounding up happens even in cases like short transfers that ends with the first block at ends at an arbitrary byte.

==== Followup transfers ====
After a DMA transfer is finished, it is possible to trigger a "followup transfer", that is a transfer that sequentially continues the previous one, by simply writing a new length to the PI_WR_LEN register. In this case, the current values of PI_DRAM_ADDR and PI_CART_ADDR are used at the beginning of the transfers. Those values will match the last addresses as updated by the first transfer.

The above section describes in details how PI reads and RDRAM writes are done, and registers are updated, so they also implicitly describe how a followup transfer behaves in various edge cases (short transfers, misaligned transfers, etc.)

==== PI_WR_LEN readbacks after a transfer ====
Reading back PI_WR_LEN after a transfer is done, appears to always be fixed at 0x7F. The only exception that has been noticed is when the transfer was smaller than 8 bytes: in that case, the value is 0x7F minus the initial RDRAM misalignment. For instance, if the RDRAM misalignment was 4, the value found in the register at the end of the transfer will be 0x7B.

==== DMA data dumps ====
To further investigate and understand how PI DMA is performed, the repo [https://github.com/rasky/n64_pi_dma_test n64_pi_dma_test] can be used. The repo contains data dumps acquires on real hardware of DMA transfers with all possible misalignments (0, 2, 4, 6), all lengths from 1 to 384 bytes, and all distances from RDRAM page end from 0 to 128 bytes. It also contains timing information on all those transfers. The repo can be used as a testsuite for emulators, but also to further investigate other side cases.
