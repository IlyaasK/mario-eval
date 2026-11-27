<!--
  Source: https://n64brew.dev/wiki/Reality_Signal_Processor/Interface
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The RSP interface is accessed by VR4300 via memory mapped registers at the physical address <code>0x040x xxxx</code>. However, because all memory accesses in the VR4300 are made using virtual addresses, it is normally used <code>0xA40x xxxx</code> to access the interface in the uncached segment.

== DMEM and IMEM ==
Both RSP memory banks are fully memory mapped into the VR4300 address space, as follows:
{| class="wikitable"
! colspan="2" |Address range
!Memory
|-
|0x04000000
|0x04000FFF
|RSP DMEM
|-
|0x04001000
|0x04001FFF
|RSP IMEM
|}
Accesses are usually performed using 32-bit reads and writes by VR4300. Different access sizes follow the standard behavior of RCP accesses documented in the [[Memory map#Physical Memory Map accesses|Memory Map]].

Since the memory is single-port, it can only be accessed by either the VR4300 or the RSP itself at the same time (including its internal DMA engine). Notice that there is no bus arbiter: an access happening at the same time by both processors will cause problems: typically what happens is that VR4300 wins the race, so the RSP write is lost, or the RSP read returns the same data read by the VR4300 (even if the address was different). Also, if a DMA was in progress, the address of the memory access performed by VR4300 becomes the current address of the DMA transfer, corrupting it. So, in general, VR4300 should access DMEM/IMEM only when RSP is halted.

== DMA transfers ==
DMA transfers can be initiated by either VR4300 or RSP. They can transfer from/to RDRAM to/from IMEM/DMEM very efficiently, much faster than copying the data word by word using VR4300 over the memory mapped addresses of the memory banks. The speed of transfer is about 3.7 bytes per VR4300 (PClock) cycle (plus some small fixed overhead). It is the fastest DMA engine in the N64.

The DMA engine allows to transfer multiple "rows" of data in RDRAM, separated by a "skip" value. This allows for instance to transfer a rectangular portion of a larger image, by specifying the size of each row of the selection portion, the number of rows, and a "skip" value that corresponds to the bytes between the end of a row and the beginning of the following one. Notice that this applies only to RDRAM: accesses in IMEM/DMEM are always linear.

DMA transfers only happen between 8-byte aligned addresses (in both RDRAM and IMEM/DMEM). DMA registers do not allow misaligned addresses to be written, as the lowest 3 bits are ignored and fixed to 0. The same applies to the length registers, so that the transfer size is always a multiple of 8.

A single DMA transfer can only transfer to/from one of DMEM or IMEM. It is not possible for instance to write data to both DMEM and IMEM in a single transfer. If the transfer hits the end of either memory area, it wraps around to the beginning of it.

=== Double buffering ===

All DMA registers are double-buffered: this means that it is possible to program a DMA transfer while another one is in progress. As soon as the first transfer finishes, the second one will start. The RSP status register reports in separate bits whether there is a transfer ongoing, and whether there is a transfer pending.

Reading from the DMA registers always return information on the ongoing transfer, or the last finished transfer. Pending values that are written to the registers can not be read back, until the transfer begins: at that point, they become visible as the transfer progresses.

== RSP Internal Registers ==
The internal RSP registers are memory mapped into the VR4300 physical address space starting from 0x0404 0000. Normally, accesses are performed through the virtual uncached segment, so at 0xA404 0000.

The exact same physical registers are also exposed as COP0 registers to RSP itself, and can thus be accessed using the MTC0 / MFC0 opcodes. Since access to all registers is shared by VR4300 and RSP, special care must be taken while writing software to decide who is in charge of each different resource / feature. For instance, normally DMA operations are performed by either the CPU or the RSP only; if the software architecture requires both to issue DMA transfers, some kind of mutex protocol must be established (for instance, using either the SIG bits in the SP_STATUS register, or the SP_SEMAPHORE register).
{| class="wikitable"
|+
!VR4300 address
!RSP COP0 register
!Name
!Description
|-
|0x0404 0000
|style="text-align: center;" |c0
|[[Reality Signal Processor/Interface#SP DMA SPADDR|SP_DMA_SPADDR]]
|Address in IMEM/DMEM for a DMA transfer
|-
|0x0404 0004
|style="text-align: center;" |c1
|[[Reality Signal Processor/Interface#SP DMA RAMADDR|SP_DMA_RAMADDR]]
|Address in RDRAM for a DMA transfer
|-
|0x0404 0008
|style="text-align: center;" |c2
|[[Reality Signal Processor/Interface#SP DMA RDLEN|SP_DMA_RDLEN]]
|Length of a DMA transfer. Writing this register triggers a DMA transfer from RDRAM to IMEM/DMEM
|-
|0x0404 000C
|style="text-align: center;" |c3
|[[Reality Signal Processor/Interface#SP DMA WRLEN|SP_DMA_WRLEN]]
|Length of a DMA transfer. Writing this register triggers a DMA transfer from IMEM/DMEM to RDRAM.
|-
|0x0404 0010
|style="text-align: center;" |c4
|[[Reality Signal Processor/Interface#SP STATUS|SP_STATUS]]
|RSP status register.
|-
|0x0404 0014
|style="text-align: center;" |c5
|[[Reality Signal Processor/Interface#SP DMA FULL|SP_DMA_FULL]]
|Report whether there is a pending DMA transfer (mirror of <code>DMA_FULL</code> bit of SP_STATUS)
|-
|0x0404 0018
|style="text-align: center;" |c6
|[[Reality Signal Processor/Interface#SP DMA BUSY|SP_DMA_BUSY]]
|Report whether there is a DMA transfer in progress (mirror of <code>DMA_BUSY</code> bit of SP_STATUS)
|-
|0x0404 001C
|style="text-align: center;" |c7
|[[Reality Signal Processor/Interface#SP SEMAPHORE|SP_SEMAPHORE]]
|Register to assist implementing a simple mutex between VR4300 and RSP.
|}

=== SP_DMA_SPADDR ===
{{#invoke:Register table|head|850px|SP_DMA_SPADDR <code>0x0404 0000</code> (RSP COP0: <code>c0</code>)}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="3" | — || MEM_BANK || colspan="4" | MEM_ADDR[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-0 || U-0 || U-0
|-
| colspan="5" | MEM_ADDR[7:3] || 0 || 0 || 0
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-13 | Undefined      | Initialized to <code>0</code>
| 12    | MEM_BANK       | Bank accessed by the transfer <br>0 {{=}} DMEM  <br>1 {{=}} IMEM
| 11-0  | MEM_ADDR[11:0] | DMEM or IMEM address used in SP DMAs. Notice that the lowest 3 bits are always 0.
}}
'''Extra Details:'''
: '''MEM_BANK'''
:: This bit selects the memory bank that will be accessed by the DMA transfer. Notice that, even though the memory banks appear to be contiguous in VR4300 address space, it is not possible to perform a single DMA transfer that spans across two banks. Each transfer will only access a single bank. For instance, to load a microcode, it is normally necessary to do two separate transfers: one for IMEM and one for DMEM.
: '''MEM_ADDR'''
:: This field contains the address in SP memory where the DMA transfer begins. The address is always aligned to 8 bytes, as the lowest 3 bits cannot be written. Notice that after writing to this register, the value is latched by SP but it is kept "pending" until the transfer is initiated via writes to <code>SP_DMA_WRLEN</code> or <code>SP_DMA_RDLEN</code>. Reads will continue returning the current (non-pending) value that refers to either an ongoing DMA transfer, or the last finished one. After a DMA transfer is finished, reading this register contains the address after the last one that was written.
: '''Reads'''
:: Reading this register while a transfer is progress returns the current SP pointer (that is, the value is updated while the transfer is in progress). Notice that this is true even if another value was previously written to this register and it is pending: see the section on double buffering above for more information.

=== SP_DMA_RAMADDR ===
{{#invoke:Register table|head|550px|SP_DMA_RAMADDR <code>0x0404 0004</code> (RSP COP0: <code>c1</code>)}}
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
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-0 || U-0 || U-0
|-
| colspan="5" | DRAM_ADDR[7:3] || 0 || 0 || 0
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-24 | Undefined | Initialized to <code>0</code>
| 23-0 | DRAM_ADDR[23:0] | RDRAM address used in SP DMAs. Notice that the lowest 3 bits are always 0.
}}
'''Extra Details:'''
: '''DRAM_ADDR'''
:: This field contains the address in RDRAM memory where the DMA transfer begins. The address is always aligned to 8 bytes, as the lowest 3 bits cannot be written. Notice that after writing to this register, the value is latched by SP but it is kept "pending" until the transfer is initiated via writes to <code>SP_DMA_WRLEN</code> or <code>SP_DMA_RDLEN</code>. Reads will continue returning the current (non-pending) value that refers to either an ongoing DMA transfer, or the last finished one. After a DMA transfer is finished, reading this register contains the address after the last one that was written.
: '''Reads'''
:: Reading this register while a transfer is progress returns the current RDRAM pointer (that is, the value is updated while the transfer is in progress). Notice that this is true even if another value was previously written to this register and it is pending: see the section on double buffering above for more information.

=== SP_DMA_RDLEN ===

This register is used to initiate a DMA transfer from RDRAM to DMEM/IMEM. It must be written as third register, after programming <code>SP_DMA_SPADDR</code> and <code>SP_DMA_RAMADDR</code>. As soon as it is written, if the DMA engine was idle, a DMA transfer is started. Otherwise, the DMA transfer is enqueued (double-buffered), waiting for the previous one to be finished.

{{#invoke:Register table|head|550px|SP_DMA_RDLEN <code>0x0404 0008</code> (RSP COP0: <code>c2</code>)}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | SKIP[11:4]
{{#invoke:Register table|row|23:16}}
| RW-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| SKIP[3] || 0 || 0 || 0 || colspan="4" | COUNT[7:4]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="4" | COUNT[3:0] || colspan="4" | RDLEN[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-0 || U-0 || U-0
|-
| colspan="5" | RDLEN[7:3] || 0 || 0 || 0
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-20 | SKIP[11:0] | Number of bytes to skip in RDRAM after each row. Notice that the lowest 3 bits are always 0.
| 19-12 | COUNT[7:0] | Number of rows to transfer minus 1.
| 21-0 | RDLEN[11:0] | Number of bytes to transfer for each row minus 1. Notice that the lowest 3 bits are always 0.
}}
'''Extra Details:'''
: '''RDLEN'''
:: Like other DMA transfers in N64, this field holds the number of bytes to transfer minus 1. Since the DMA engine works in 64-bit words, writing 0 (or any value up to and including 7) starts a transfer of exactly 8 bytes. After the DMA transfer is finished, this field contains the value <code>0xFF8</code>; the reason is that the field is internally decremented by 8 for each transferred word, so the final value will be <code>-8</code> (in hex, <code>0xFF8</code>
: '''COUNT and SKIP'''
:: Setting <code>COUNT</code> to 0 initiates a linear transfer of <code>RDLEN</code> plus 1 bytes (rounded up to 8 bytes); in this case, the value of <code>SKIP</code> is effectively ignored as only one row is transferred. With any other value, <code>COUNT</code> indicates the number of rows, to transfer a portion of a rectangular image, and <code>SKIP</code> indicates the so-called row stride, that is number of bytes to add to jump from the end of a row to the beginning of next one. After a DMA transfer is finished, <code>COUNT</code> is reset to 0, and <code>SKIP</code> is unchanged.
: '''Reads'''
:: Reading this register while a transfer is progress returns the updated <code>RDLEN</code> and <code>COUNT</code> values (that is, the value is updated while the transfer is in progress). Notice that this is true even if another value was previously written to this register and it is pending: see the section on double buffering above for more information. Notice also that <code>SP_DMA_WRLEN</code> and <code>SP_DMA_RDLEN</code> both always returns the same data on read, relative to the current transfer, irrespective on the direction of the transfer.

=== SP_DMA_WRLEN ===

This register is used to initiate a DMA transfer from DMEM/IMEM to RDRAM. It must be written as third register, after programming <code>SP_DMA_SPADDR</code> and <code>SP_DMA_RAMADDR</code>. As soon as it is written, if the DMA engine was idle, a DMA transfer is started. Otherwise, the DMA transfer is enqueued (double-buffered), waiting for the previous one to be finished.

{{#invoke:Register table|head|550px|SP_DMA_WRLEN <code>0x0404 000C</code> (RSP COP0: <code>c3</code>)}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | SKIP[11:4]
{{#invoke:Register table|row|23:16}}
| RW-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| SKIP[3] || 0 || 0 || 0 || colspan="4" | COUNT[7:4]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="4" | COUNT[3:0] || colspan="4" | WRLEN[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-0 || U-0 || U-0
|-
| colspan="5" | WRLEN[7:3] || 0 || 0 || 0
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-20 | SKIP[11:0] | Number of bytes to skip in RDRAM after each row. Notice that the lowest 3 bits are always 0.
| 19-12 | COUNT[7:0] | Number of rows to transfer minus 1.
| 21-0 | WRLEN[11:0] | Number of bytes to transfer for each row minus 1. Notice that the lowest 3 bits are always 0.
}}
'''Extra Details:'''
Please refer to <code>SP_DMA_RDLEN</code> for details.

=== SP_STATUS ===
The SP_STATUS register is the main status register for the RSP. Like many other flag registers in N64, it has two different layouts when accessed for reading and writing: this allows to perform atomic set / clear operations on each flag using a simple memory write operation, without risking race conditions that would be frequent if a read-modify-write sequence was issued by the processor. Note that writing both the set and clear bits for a particular flag in the same write results in no effect, the prior state of the flag is preserved. {{#invoke:Register table|head|850px|SP_STATUS <code>0x0404 0010</code> (RSP COP0: <code>c4</code>) - Read access}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0
|-
| — || SIG7 || SIG6 || SIG5 || SIG4 || SIG3 || SIG2 || SIG1
{{#invoke:Register table|row|7:0}}
| R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0
|-
| SIG0 || INTBREAK || SSTEP || IO_BUSY || DMA_FULL || DMA_BUSY || BROKE || HALTED
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 7-14 | SIG<n> | Status of the 8 custom bits that can be freely used to communicate state between VR4300 and RSP.
| 6 | INTBREAK | Configure the RSP to trigger a RSP MI interrupt when the <code>BREAK</code> is run. <br>0 {{=}} When <code>BREAK</code> is run, just halt the RSP core without triggering a RSP MI interrupt.  <br>1 {{=}} When <code>BREAK</code> is run, halt the RSP core and trigger a MI interrupt.
| 5 | SSTEP | Set to <code>1</code> when single-step mode is activated. In single-step mode, RSP auto-halts itself after a single opcode is run. See the details below.
| 4 | IO_BUSY | Set to <code>1</code> when the RSP is accessing either DMEM or IMEM. (*TODO*: verify this)
| 3 | DMA_FULL | Set to <code>1</code> when there is a DMA transfer pending in the DMA register in addition to a DMA already in progress.
| 2 | DMA_BUSY | Set to <code>1</code> when there is a DMA transfer currently in progress.
| 1 | BROKE | Set to <code>1</code> when the RSP executes a <code>BREAK</code> opcode. It must be manually reset.
| 0 | HALTED | Current running status of the RSP  <br>0 {{=}} Running  <br>1 {{=}} Idle / halted
}}

{{#invoke:Register table|head|1050px|SP_STATUS <code>0x0404 0010</code> (RSP COP0: <code>c4</code>) - Write access}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || W-0
|-
| — || — || — || — || — || — || — || SET_SIG7
{{#invoke:Register table|row|23:16}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| CLR_SIG7 || SET_SIG6 || CLR_SIG6 || SET_SIG5 || CLR_SIG5 || SET_SIG4 || CLR_SIG4 || SET_SIG3
{{#invoke:Register table|row|15:8}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| CLR_SIG3 || SET_SIG2 || CLR_SIG2 || SET_SIG1 || CLR_SIG1 || SET_SIG0 || CLR_SIG0 || SET_INTBREAK
{{#invoke:Register table|row|7:0}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| CLR_INTBREAK || SET_SSTEP || CLR_SSTEP || SET_INTR || CLR_INTR || CLR_BROKE || SET_HALT || CLR_HALT
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 9-24 | CLR_SIG<n>/SET_SIG<n> | Set to <code>0</code> or <code>1</code> the 8 available bitflags that can be used as communication protocol between RSP and CPU.
| 8 | SET_INTBREAK | Enable the <code>INTBREAK</code> flag. When this flag is enabled, running a <code>BREAK</code> opcode will generate a RSP MI interrupt, in addition to halting the RSP.
| 7 | CLR_INTBREAK | Disable the <code>INTBREAK</code> flag. When this flag is disabled, running a <code>BREAK</code> opcode will not generate any RSP MI interrupt, but it will still halt the RSP.
| 6 | SET_SSTEP | Enable single-step mode. When this mode is activated, the RSP auto-halts itself after every opcode that is run. The VR4300 can then trigger a new step by unhalting it.
| 5 | CLR_SSTEP | Disable single-step mode.
| 4 | SET_INTR | Manually trigger a RSP MI interrupt on the VR4300. It might be useful if the RSP wants to manually trigger a VR4300 interrupt at any point during its execution.
| 3 | CLR_INTR | Acknowledge a pending RSP MI interrupt. This must be done any time a RSP MI interrupt was generated, otherwise the interrupt line on the VR4300 will stay asserted.
| 2 | CLR_BROKE | Clear the <code>BROKE</code> flag, that is automatically set every time a <code>BREAK</code> opcode is run. This flag has no effect on the running/idle state of the RSP; it is just a latch that remembers whether a <code>BREAK</code> opcode was ever run.
| 1 | SET_HALT | Pause running RSP code (set the <code>HALTED</code> flag)
| 0 | CLR_HALT | Start running RSP code from the current RSP PC (clear the <code>HALTED</code> flag)
}}

'''Extra Details:'''
: '''HALT'''
:: The HALT flag can be thought of as a "pause" flag. When the RSP is halted by writing the <code>SET_HALT</code> bit, the RSP core pauses the pipeline without flushing it, maintaining the current PC but also the intermediate status like pending writebacks and delay slots. If a new ucode is loaded instead, make sure to also write SP_PC to the new entry point (writing to SP_PC also fully discards the RSP core pipeline). Given the "pause" behavior, it would look like the VR4300 could pause and unpause the RSP at any time during its execution without side effects. Unfortunately, this only works "most" of the time: there is at least one hardware bug that can cause corruption when a halt is triggered within a specific sequence of opcodes. This bug has been [https://github.com/DragonMinded/libdragon/blob/2c8b04b7f08fe5e732101fe64d23590f464d6b51/include/rsp_queue.inc#L254-L259 observed during libdragon development], but the developers could not manage to isolate it or reduce it to a small snippet of code. In general, it is thus very risky to prepare a communication protocol that comprehends VR4300 pausing/unpausing the RSP at random times while it is running.
: '''HALT and DMA'''
:: Setting the HALT bit does not pause the DMA transfers in progress. The DMAs will continue running until they finish. This will be reflected by the status register, so that it is possible that both <code>HALT</code> and <code>DMA_BUSY</code> are set. This is specifically important if VR4300 halts the RSP and wants to access IMEM/DMEM immediately: it is important to wait for <code>DMA_BUSY</code> to be cleared before accessing the memory banks, or corruption can happen (see above for more information on what happens when both VR4300 and RSP access the memory banks at the same time).
: '''SSTEP'''
:: The single step mode allows the RSP to execute a single instruction and pause itself. In particular, whenever <code>SSTEP</code> is set while the RSP is running, RSP will pause itself before next instruction by setting the <code>HALT</code> flag. To perform single-stepping through RSP code, VR4300 should set the <code>SSTEP</code> flag and then reset <code>HALT</code> to execute exactly one instruction. Unfortunately, this hardware mode is very buggy. There are at least two specific bugs that have been isolated. The presence of these two bugs are enough to consider the feature broken beyond any expectation of being useful. 
::* Conditional branch instructions are sometimes broken; that is a branch is taken where it should not or viceversa
::* <code>MTC0</code> / <code>MFC0</code> are broken: the instructions have a 2-cycle latency but it looks like the pending writeback is lost in single step mode; <code>MFC0</code> actually writes <code>(PC+4)/4</code> into the register (where <code>PC</code> is the address of the <code>MFC0</code> instruction itself). <code>MTC0</code> simply doesn't work, and the target register is not written.
: '''SIG<n>'''
::Signal bits are software-controlled bits with no hardware meaning. They can be set or reset by writing to the status register. Since both VR4300 and RSP can access the status register, they can be used to perform a simple communication / handshaking protocol between the two CPUs. For instance the RSP might set <code>SIG0</code> to <code>1</code> when some data has been processed and sent back to RDRAM via DMA, so that VR4300 can access the results after it sees <code>SIG0</code> being set. Because of the design of the hardware register that allows for atomic modification of bits thanks to the separate write access structure, it is possible for VR4300 and RSP to set/reset different signal bits at the same time without risking race conditions.
:'''DMA_FULL''' 
::This bit is set whenever a DMA transfer is pending, that is it has been programmed via the DMA registers but it has not started yet because another transfer is in progress. This is possible because of the double-buffering of the DMA registers (explained above). Notice that this bit goes to <code>0</code> a few clock cycles *before* the previous DMA transfer is finished (probably the RSP internally has some preparation work for DMA that is able to parallelize with the last memory writes of another transfer). Anyway, as soon as the bit goes to zero, it is possible to enqueue a new DMA transfer.

===SP_DMA_FULL===
{{#invoke:Register table|head|750px|SP_DMA_FULL <code>0x0404 0014</code> (RSP COP0: <code>c5</code>)}}
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
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || R-0
|-
| — || — || — || — || — || — || — || DMA_FULL
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-1 | Undefined | Initialized to <code>0</code>
| 0 | DMA_FULL | Mirror of DMA_FULL bit in SP_STATUS
}}

===SP_DMA_BUSY===
{{#invoke:Register table|head|750px|SP_DMA_FULL <code>0x0404 0018</code> (RSP COP0: <code>c6</code>)}}
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
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || R-0
|-
| — || — || — || — || — || — || — || DMA_BUSY
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-1 | Undefined | Initialized to <code>0</code>
| 0 | DMA_BUSY | Mirror of DMA_BUSY bit in SP_STATUS
}}

===SP_SEMAPHORE===
{{#invoke:Register table|head|1050px|SP_SEMAPHORE <code>0x0404 001C</code> (RSP COP0: <code>c7</code>)}}
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
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0
|-
| — || — || — || — || — || — || — || SEMAPHORE
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-1 | Undefined | Initialized to <code>0</code>
| 0 | SEMAPHORE | Semaphore bit to implement a hardware-assisted mutex with atomic access. The bit behaves normally on reads and writes, with the only difference that after each read, the bit is always automatically set to 1 by the hardware (though the previous value is returned). }}
'''Extra Details:'''
:'''SEMAPHORE'''
::The goal of this bit is to help implementing a mutex between VR4300 and RSP. The mutex can be used to guard access to any shared hardware resource, a typical example being the DMA engine. To acquire the mutex, the CPU (either VR4300 or RSP) should spin reading the <code>SEMAPHORE</code> bit until it reads 0. At that point, the bit is automatically flipped to 1 by the hardware, so reading 0 means "the semaphore was free, and you have just acquired it". After the CPU is done using the shared resource, it can simply write 0 to <code>SEMAPHORE</code> to release it.

==RSP PC register==
RSP has an internal PC (program counter) register that cannot be explicitly accessed via RSP opcodes. Instead, a memory mapped register is available to VR4300 to control the RSP PC while RSP is halted. The register is called <code>SP_PC</code>.

Notice that VR4300 is allowed to access SP_PC only while RSP is halted. Reading from SP_PC while RSP is running returns garbage data, and writing to it causes RSP to misbehave.

===SP_PC===
{{#invoke:Register table|head|550px|SP_PC <code>0x0408 0000</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | PC[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || R-0 || R-0
|-
| colspan="6" | PC[7:2] || 0 || 0
{{#invoke:Register table|foot}}{{#invoke:Register table|definitions
| 31-12 | Undefined | Initialized to <code>0</code>
| 11-0 | PC[11:0] | Read/write the RSP PC (program counter). Notice that the lowest two bits are always 0.
}}
'''Extra Details:'''
:'''PC''' 
::Reads while RSP is running returns random bits. Reads while RSP is halted return the address of the instruction that the RSP will execute when it is unhalted. <br>Writes will also reset the RSP CPU core pipeline, so any pending writeback or branch are discarded.
