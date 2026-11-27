<!--
  Source: https://n64brew.dev/wiki/RDRAM_Interface
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The RDRAM Interface (or '''RI''') is one of multiple I/O interfaces in the RCP. It acts as a controller for the RDRAM channel to which one or more RDRAM modules are connected. It converts memory accesses from the system into RDRAM protocol commands for the RDRAM bus. The RI integrates a RDRAM ASIC Cell (or '''RAC''') in order to take care of the low level details of the RDRAM bus. Further details about such a RAC can be found in [https://www.datasheetarchive.com/pdf/download.php?id=04f8a219efa5e2304d0e403c3f77e759adedf8&type=O&term=rac%2520rdram datasheets for similar RACs] (however not necessarily the same version used by the N64).

There are two sets of memory mapped registers for RDRAM configuration. One set is specifically for writing to or reading from the configuration registers in one or all individual [[RDRAM]] module(s). The other set, defined in the next section, configure this RDRAM interface. Refer to [[Memory map]] for the full map, including all RDRAM-related segments.

The base address for these registers is <code>0x0470 0000</code>, also known as RI_BASE. However, because all memory accesses in the CPU are made using virtual addresses, the following addresses must be offset appropriately. For non-cached reads/writes, add <code>0xA000 0000</code> to the address. As an example, to directly write to the RI_MODE register, use address <code>0xA470 0000</code>.

Some information is available in [https://patentimages.storage.googleapis.com/cc/33/96/6e54e1628ec0f9/US6593929.pdf US6593929.pdf] in paragraph "Example Memory Controller/Interface Registers" and associated figures (37A-H).

= Registers =
'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at boot
-? = Unknown default value
[x:y] = Specifies bits x to y, inclusively</pre>
==== <span style="display:none;">0x0470 0000 - RI_MODE ====
----
{{#invoke:Register table|head|600px|RI_MODE <code>0x0470 0000</code>}}
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
| U-0 || U-0 || U-0 || U-0 || RW-1 || RW-1 || RW-? || RW-?
|-
| — || — || — || — || STOP_R || STOP_T || colspan="2" | OP_MODE[1:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-4 | Undefined | Initialized to <code>0</code>
| 3 | STOP_R | Automatic halting of RAC clock used for receive logic when not in use, normally enabled. <br>1 {{=}} Enabled <br>0 {{=}} Disabled
| 2 | STOP_T | Automatic halting of RAC clock used for transmit logic when not in use, normally enabled. <br>1 {{=}} Enabled <br>0 {{=}} Disabled
| 1-0 | OP_MODE[1:0] | Controls how Serial Mode (SMode) packets are sent to RDRAM modules. [http://www.bitsavers.org/components/nec/_dataBooks/1995_NEC_Application_Specific_Memory.pdf] Usually set to <code>10</code>. <br>11 {{=}} Unknown <br>10 {{=}} Sends a packet before each RDRAM transaction. Tells the modules to enter standby mode after receiving each transaction. <br>01 {{=}} Sends a packet every 4 BusClk cycles. Tells the modules to always be active (consumes more power and usually not used). <br>00 {{=}} Sends continuous packets. After 272 BusClk cycles, all RDRAM modules will enter a reset mode. <br>{{spaces|4}}<i>Due to the timing differences, some changes will require a delay to become active.</i>
}}

==== <span style="display:none;">0x0470 0004 - RI_CONFIG ====
----
{{#invoke:Register table|head|600px|RI_CONFIG <code>0x0470 0004</code>}}
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
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| — || AutoCC || colspan="6" | CC [5:0]
{{#invoke:Register table|foot}}
<pre>
READ?/WRITE:
    [6]      Enable/Disable automatic current calibration from controller. Corresponds to the RAC CCtlEn input signal.
             It selects whether the value CC[5:0] will be written to current control register (AutoCC=0), or if an internally generated value should be used (AutoCC=1).
    [5:0]    Current Control Input. The value to be loaded into current control register when AutoCC is disabled. Corresponds to the RAC CCtlI input signal.
</pre>


==== <span style="display:none;">0x0470 0008 - RI_CURRENT_LOAD ====
----
{{#invoke:Register table|head|550px|RI_CURRENT_LOAD <code>0x0470 0008</code>}}
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
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|foot}}
<pre>
WRITE:
     Any write to this register causes a new value to be loaded into the RAC current control register. Corresponds to the RAC CCtlLd input signal.
     The value loaded depends on the contents of the RI_CONFIG register, see there for details.
     TOVERIFY: When AutoCC=1 in RI_CONFIG and this register is written, a sufficient delay should be observed to let CC autocalibration stabilize.

READ:
     This register is intended to be write-only, the read behavior is unintended and returns a collection of bits from other registers:
        [0] : RI_ERROR Ack
        [1] : 1                     TOVERIFY always 1?
        [2] : 1                     TOVERIFY always 1?
        [3] : RI_MODE STOP_R
        [4] : RI_SELECT TSEL[0]
     [32:5] : 0                     TOVERIFY always 0?
</pre>

==== <span style="display:none;">0x0470 000C - RI_SELECT ====
----
{{#invoke:Register table|head|550px|RI_SELECT <code>0x0470 000C</code>}}
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
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| colspan="4" | TSEL [3:0] || colspan="4" | RSEL [3:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-8 | Undefined | Undefined
| 7-4 | TSEL[3:0] | Configure transmit signals timings. Corresponds to RAC signals B{C,D,E}Sel.
| 3-0 | RSEL[3:0] | Configure receive signals timings. Corresponds to RAC signals R{C,D}Sel.
}}

'''Extra Details:'''
IPL3 configures TSEL to <code>0b0001</code> and RSEL to <code>0b0100</code>. It is currently unclear if this is the only valid configuration.

==== <span style="display:none;">0x0470 0010 - RI_REFRESH ====
----
{{#invoke:Register table|head|550px|RI_REFRESH <code>0x0470 0010</code>}}
{{#invoke:Register table|row|31:24}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| — || colspan="4" | MultiBank[3:0] || Opt || En || Bank
{{#invoke:Register table|row|15:8}}
| RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| colspan="8" | DirtyRefreshDelay [7:0]
{{#invoke:Register table|row|7:0}}
| RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| colspan="8" | CleanRefreshDelay [7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-?? | Undefined | Undefined
| ??-19| MultiBank[3:0] | Bitfield indicating multibank RDRAM modules. Up to four multibank modules are tracked, enough to fill 8MiB with 4x2MiB modules. <br>Probably why RDRAM modules are re-ordered with multibanks modules first during initialization in IPL3.
| 18 | Opt | Optimize. Usually set to <code>0x1</code>.
| 17 | En | Automatic Refresh Enable. Usually set to <code>0x1</code>.
| 16 | Bank | Oscillates between 0 and 1 during operation.
| 15-8 | DirtyRefreshDelay[7:0] | Cycles to delay after refresh when the bank was previously dirty. Usually set to <code>54</code>, which is <code>tRETRYREFRESHDIRTY / 4</code>.
| 7-0 | CleanRefreshDelay[7:0] | Cycles to delay after refresh when the bank was previously clean. Usually set to <code>52</code>, which is <code>tRETRYREFRESHCLEAN / 4<code/>.
}}

'''Extra Details:'''
: The automatic refresh operation, when enabled, is triggered by VI HSYNC timing. This forces the refresh operation to happen during HBLANK so it can't block VI scanout. 
: As a single RDRAM refresh command refreshes 2 rows on all banks, the standard NTSC/PAL video timings result in refreshing all 512 rows in 15.6ms or 16.4ms respectively, meeting the RDRAM spec of 17ms.
: VI HSYNC defaults to 41us on power-cycle. This results in a 10.5ms refresh cycle, causing a noticeable memory bandwidth reduction until the VI is configured.

==== <span style="display:none;">0x0470 0014 - RI_LATENCY ====
----
{{#invoke:Register table|head|550px|RI_LATENCY <code>0x0470 0014</code>}}
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
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-? || U-? || U-? || U-? || RW-? || RW-? || RW-? || RW-?
|-
| — || — || — || — || colspan="4" | DmaLatencyOverlap[4:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-4 | Undefined | Undefined
| 3-0 | DmaLatencyOverlap[4:0] | ? Defaults to <code>0xf</code>
}}

'''Speculation:'''

: This might control the maximum size of DMA transfers. RCP supports DMA bursts of upto 16 Octbytes (128 bytes), which matches the default value.<Br> Perhaps this register allows forces a smaller transfer size and allows better interleaving of multiple DMA requests, or for a lower guaranteed latency when a high-priority device (like VI) requests a DMA transfer.
: This register isn't used by any known N64 software, maybe it's broken. Maybe it didn't improve performance.

==== <span style="display:none;">0x0470 0018 - RI_ERROR ====
----
{{#invoke:Register table|head|550px|RI_ERROR <code>0x0470 0018</code>}}
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
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-? || U-? || U-? || U-? || U-? || R-? || R-? || R-?
|-
| — || — || — || — || — || Over || Nack || Ack 
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-3 | Undefined | Undefined
| 2 | Over | OverRangeError. Set when reading/writing any addresses in the range <code>0x0080 0000</code> to <code>0x03EF FFFF</code>, even if an RDRAM bank has been mapped there. However note that request packets are still sent out over the RDRAM bus even if this error was flagged.
| 1 | NAck | UnexpectedNAck. Set when RI sees an unexpected NAak (probably because bank status bits were wrong).
| 0 | Ack | MissingAck. Set when RI doesn't see an Ack (like when no RDRAM device was mapped to that address). <br>
This bit is set sometime during IPL3 init, presumably due to probing memory size.
}}

Writing any value this register will clear any errors.

==== <span style="display:none;">0x0470 001c - RI_BANK_STATUS ====
----
{{#invoke:Register table|head|550px| RI_BANK_STATUS <code>0x0470 001c</code>}}
{{#invoke:Register table|row|31:24}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="8" | BankDirtyBits[7:0]
{{#invoke:Register table|row|7:0}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="8" | BankValidBits[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-16 | Undefined | Undefined
| 15-8 | BankDirtyBits[7:0] | One per bank. Set when the currently open row has been written. Cleared when a new row is opened but not yet written to.
| 7-0 | BankValidBits[7:0] | One per bank. Set when a row is opened. Presumably only cleared by a refresh cycle.
}}

Writing any value to this register will set all valid bits to 0 and all dirty bits to 1. This causes the RI to become out-of-sync with RDRAM and will result in errors.<br>
Memory read/write requests to banks mapped above 8MiB do not update any of these bits. This may also cause out-of-sync errors as the RI appears to be unable to track the current open row state for banks above 8MiB.

'''Note:''' Some sources such as libultra's <code>rcp.h</code> header call this register <code>RI_WERROR</code>, however this register is unrelated to errors. The name <code>RI_BANK_STATUS</code> comes from a patent and is much more descriptive of the function of this register.

= Bank Status Tracking =
Each 1 MiB bank can only have one row (2 KiB) open. The only way to open a row on with version 1 of the Rambus spec is to just attempt a read or write operation. If the row is already open, the operation succeeds (hits) and the Rambus device responds with an Ack packet. If the row wasn't open, the operation fails and the Rambus device responds with a NAck packet, while simultaneously closing the currently open row and loading the next. This takes even longer if the current row is dirty and needs to be written back to the dram array first. The Controller must send a new request packet once the device has finished opening the row.

One possible implementation for a Rambus controller is to just retry any operations that miss, they will eventually succeed. But RI doesn't have any retry logic. It does detect unexpected NAcks and set the '''<small>NAck</small>''' bit in the '''RI_ERROR''' register.

Instead, RI tracks the current status of the state machine for each bank. Some of this shadow state machine is exposed via the '''RI_BANK_STATUS''' register where you can find the row valid and row dirty bits. The '''<small>MultiBank</small>''' field of the '''RI_REFRESH''' register also has some effect, as the two banks of a 2MiB chip share some resources. ''(Research Needed, exactly which timings are affected by Multibank?)'' Other parts of the shadow state machine are not exposed via registers, such as if the chips are currently executing a refresh operation, or which row is currently open. With this state tracking, RI always knows which requests will cause a miss and how long it needs to wait before resending the request packet.

RI only has resources for tracking 8 banks (of 1 MiB each, for a total of 8 MiB) and these banks are hardwired into the bottom 8 MiB of the memory-space, as 8 continuous banks.

While you could initialise more Rambus devices in the space above 8 MiB, or move one of the existing devices, without Bank Status tracking, the timings will be wrong ''(Research Needed, wrong in what way, presumably RI always assumes operations will always hit?).''

Bank Status Tracking also interferes with any attempt to use the Rambus' Address Swapping feature, as there is no way to configure Bank Status tracking's address to match the new layout.

= Memory addressing =
RI translate memory accesses in the range <code>0x0000 0000</code> - <code>0x03FF FFFF</code> into suitable RDRAM protocol packets with proper command type and 36 bit address. See [[RDRAM|RDRAM addressing]] paragraph for details about how 36bit addresses are interpreted.

Address conversion done by RI (TOVERIFY):
{| class="wikitable"
! colspan="2" |Address Range
!Adr[35:29]
!Adr[28:20]
!Adr[19:11]
!Adr[10:0]
!BCastRWrite
!Description
|-
|<code>0x0000 0000</code>
|<code>0x007F FFFF</code>
|0
|(address >> 20) & 0x3F
|(address >> 11) & 0x1FF
|address & 0x7FF
|0
|Memory-space access
|-
|<code>0x0080 0000</code>
|<code>0x03EF FFFF</code>
|0
|(address >> 20) & 0x3F
|(address >> 11) & 0x1FF
|address & 0x7FF
|0
|Broken Memory-space access
Not covered by bank status tracking
|-
|<code>0x03F0 0000</code>
|<code>0x03F7 FFFF</code>
|0
|(address >> 10) & 0x1FF
|(address >> 10) & 0x1FF
|address & 0x3FF
|(address >> 19) & 0x1 == 0
|Register-space access
|-
|<code>0x03F8 0000</code>
|<code>0x03FF FFFF</code>
|0
|(address >> 10) & 0x1FF
|(address >> 10) & 0x1FF
|address & 0x3FF
|(address >> 19) & 0x1 == 1
|Broadcast register write
|}
Examples :

Assuming a standard RDRAM configuration of 4x2x9Mbit RDRAM each with IdField = 2*k for module k = 0..3 and SwapField = 0 for all modules (eg. no address swapping, Adr = AdrS).

* Reading at address 0x003A BCDE, gives the following Adr[35:20] = 3, Adr[19:0] = 0xABCDE, BCastRWrite = 0. Since we have 2x9Mbit modules, Adr[20] is ignored for Id matching and therefore RDRAM with IdField == 2 gives a match. This means RDRAM module 1 will be read at address 0x1ABCDE.
* Writing at address 0x03F0 0808, gives Adr[35:20] = 2, Adr[19:0] = 8, BCastRWrite = 0. Which means writing to RDRAM module 1 delay register.
* Writing at address 0x03F8 0008, gives BCastRWrite = 1, Adr[19:0] = 8. Which means broadcast writing to all RDRAM modules delay registers.

Remarks :

* Early version of RCP reserved fewer bits for RDRAM register address (eg. Adr[35:20] = (address >> 9) & 0x3FF; Adr[19:0] = address & 0x1FF) which didn't allow to access RDRAM register 128 (Row register) which is at offset 0x200.
* The presented address map has space for upto 32x 2x9Mbit RDRAM modules. However, a RI only has bank tracking resources for 8MiB.
* Standard DRAM initialization only supports up to 8 modules, but can mix 2x9Mbit and 1x9Mbit modules. In that case, 2x9Mbit modules are placed before 1x9Mbit modules.
* Standard DRAM initialization procedure, doesn't make use of address swapping feature, because bank tracking doesn't support it.
* Register-space addresses duplicates the content between Adr[28:20] and Adr[19:11] to not be affected by RDRAM address swapping features. Indeed, whereas address swapping is desirable for RDRAM memory to benefit from row internal row caching, registers won't benefit from the swapping and would complicate usage of registers in such a case.

==== Accesses outside of mapped RDRAM chips ====
Memory-space accesses (0x00000000 - 0x03EFFFFF) that hit addresses where there is no RDRAM chip mapped will result in a sort of "no-operation" behavior: reads will return zero, and writes will be ignored. For instance, in a N64 with 4 MiB (no expansion pak), reads at the 5 MiB are not a mirror of the reads at the first MiB: they just return zero because no chips in the RAMBUS will reply to those requests.

The same goes for accessing addresses above 8 MiB, no Rambus device will respond to requests.

This is true in theory for RDRAM buses, but there seems to be a weird behavior, at least during reads, causing some areas of the address space to return non-zero values when read. These 32-bit non-zero values can be seen every 0x80 bytes, in an area of 8 KiB, repeating every 512 KiB. The dump below has been taken from a N64; an identical pattern can be observed on different consoles, though an extensive comparison has not been run. You can see the non-zero values present in 32-bit slots every 0x80 bytes (though not all slots contain a value), in range 0 - 8KiB (0x2000), and then repeating again after 512 KiB (0x80000 - 0x82000), and so on every 512 KiB.

What seems to happen is that somehow a RDRAM register value is shown as part of a memory read; this is probably a RI bug, but it has not been fully investigated yet. For instance, the value <code>0xb4190010</code> shown at several addresses (eg: 0x1400) is a very common value for the [[RDRAM#0x00 - DeviceType|RDRAM register DeviceType]].

<syntaxhighlight lang="text">
00000  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
00380  78 01 fe 02 00 00 00 00  00 00 00 00 00 00 00 00   |x...............|
*
00d80  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
00d90  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
00e40  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
00e50  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
00f80  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
00f90  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
01380  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
01390  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
01400  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
01410  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
01480  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
01490  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
01540  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
01550  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
01600  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
01610  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
016c0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
016d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
01740  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
01750  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
804c0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
806c0  94 01 fe 02 00 00 00 00  00 00 00 00 00 00 00 00   |................|
806d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80700  9c 01 fe 02 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80710  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80780  a6 01 fe 02 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80790  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
807c0  ae 01 fe 02 00 00 00 00  00 00 00 00 00 00 00 00   |................|
807d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80840  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80850  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
808c0  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
808d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80940  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80950  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
809c0  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
809d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80a40  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80b80  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80b90  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80bc0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80bd0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80c40  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80c50  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80cc0  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80cd0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80d40  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80d50  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80dc0  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80dd0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80ec0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80ed0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
80fc0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
80fd0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81380  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81390  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81480  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81490  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
815c0  b4 19 00 10 00 00 00 00  00 00 00 00 00 00 00 00   |................|
815d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
816c0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
816d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81700  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81710  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81780  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81790  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
817c0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
817d0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81ac0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81ad0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81b00  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81b10  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81b80  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81b90  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
81bc0  fe 03 fe 03 00 00 00 00  00 00 00 00 00 00 00 00   |................|
81bd0  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   |................|
*
</syntaxhighlight>


= Count =
RCP supports DMA bursts upto a maximum of 128 bytes (16 Octwords)

The recommended mapping the Rambus request Count field from the Rambus datasheet is <code>Count = NumBytes + Address[2:0]</code>, as this produces the correct byte masking for writes that aren't 64bit aligned. But RI actually implements this mapping from the RCP as:<syntaxhighlight>
Count[6:3] = NumBytes[6:3]
Count[2:0] = NumBytes[2:0] + Address[2:0]
</syntaxhighlight>Which drops any carries from bit 2 to bit 3. This works fine for unaligned writes that fit within a single 64bit transfer (and all unaligned writes from the CPU fit this rule). 

But you can use PI to create misaligned DMA bursts of any length from 1 to 128 bytes, and it's possible to cause a dropped carry. Testing shows this results in the DMA transfers of <code>NumBytes - Address[2:0]</code> bytes. It's possible to compensate for this "bug" by increasing the transfer length (at least for short transfers under 128 bytes).

SI also allows for misaligned DMA transfers, but exact results haven't been documented. All other devices don't allow the lower bits of address to be set. 

= RI_SELECT configurations =

<big>'''Warning: This section contains speculative information that is in need of further research.'''</big>

It is currently unclear what the full set of working configurations for the TSEL and RSEL fields of RI_SELECT are. A datasheet for a Rambus Memory Controller (RMC), a component similar in function to the RI that interfaces with a Rambus ASIC Cell (RAC), refers to the IPL3 configuration (<code>TSEL=0b0001, RSEL=0b0100</code>) as "Option A". The same datasheet mentions an alternative configuration, "Option Z", configured with (<code>TSEL=0b0010, RSEL=0b1000</code>) and considers this configuration preferable over Option A:
{{Blockquote
|text=Option Z is the recommended timing option for the RMC. This minimizes the setup times of all inputs.
|author=RMC datasheet
}}
Option Z has been tested on hardware and does not appear to cause noticeable instability in RDRAM operation, although it is still unclear whether the claim about Option Z being preferable is applicable to the RI. Other "random" configurations for TSEL and RSEL were also attempted but these quickly crashed, however it is still unclear whether the two options mentioned by the RMC datasheet are the extent of possible configurations, and which configuration should be preferred on N64.
