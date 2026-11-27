<!--
  Source: https://n64brew.dev/wiki/MIPS_Interface
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The MIPS Interface (or '''MI''') is one of multiple I/O interfaces in the RCP. It is the interface between the RCP and the VR4300 CPU, primarily used for enabling/disabling interrupts and checking their status.

Memory mapped registers are used to configure the MIPS Interface. The base address for these registers is <code>0x0430 0000</code>, also known as MI_BASE. However, because all memory accesses in the CPU are made using virtual addresses, the following addresses must be offset appropriately. For non-cached reads/writes, add <code>0xA000 0000</code> to the address. As an example, to directly write to the MI_MODE register, use address <code>0xA430 0000</code>.

Note that some of these registers have different behavior when writing to them, than when reading from them. When writing to a register that has Set and Clear bits, write a 1 on the desired bit. Writing 0's have no effect. When writing 1's to both Set and Clear bits in a pair at the same time results in no effect, the previous state is preserved.

Accesses beyond <code>0x0430 0010</code> are mirrored, so only the least significant four bits are taken into account for address decoding.

(Note that this isn't the case on the iQue Player.)

= Registers =
'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at power on
[x:y] = Specifies bits x to y, inclusively</pre>
==== <span style="display:none;">0x0430 0000 - MI_MODE</code> ====
----

'''When Reading:'''

{{#invoke:Register table|head|550px|MI_MODE <code>0x0430 0000</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || W-0 || W-0 || W-0 || W-0 || R-0 || R-0
|-
| — || — || — || — || — || — || Upper || Ebus
{{#invoke:Register table|row|7:0}}
| R-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| Repeat || colspan="7" | RepeatCount[6:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 9 | Upper | Upper mode enabled. 
| 8 | EBus | EBus mode enabled.
| 7 | Repeat | Repeat mode enabled, Automatically clears after a single Rambus write. 
| 6-0 | RepeatCount[6:0] | Number of bytes (minus 1) to write in repeat mode
}}

'''When Writing:'''

{{#invoke:Register table|head|550px|MI_MODE <code>0x0430 0000</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || W-0 || W-0 || W-0 || W-0 || RW-0 || RW-0
|-
| — || — || Set Upper || Clear Upper || ClearDP || Set Ebus || Clear Ebus || Set Repeat
{{#invoke:Register table|row|7:0}}
| W-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-0 || RW-0 || RW-0
|-
| Clear Repeat || colspan="7" | RepeatCount[6:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 13 | SetUpper | Set Upper mode.
| 12 | ClearUpper | Clear Upper mode.
| 11 | ClearDP | Clear the DP Interrupt.
| 10 | SetEBus | Set Ebus mode.
| 9 | ClearEBus | Clear Ebus mode.
| 8 | SetRepeat | Set repeat mode. Automatically clears after a single Rambus write.  
| 7 | ClearRepeat | Clear repeat mode.
| 6-0 | RepeatCount[6:0] | Number of bytes (minus 1) to write in repeat mode
}}

'''MI's Mode:'''

The mode controls how reads and writes coming from the CPU are forwarded into RDRAM (technically, how 32bit SysAD bus transfers are mapped onto DBus and EBus, which are the internal RCP buses that transfer data from and to RDRAM).

RI only uses 64bit aligned reads/writes when accessing RDRAM. For operations smaller than 64bits, the data needs to be shifted into the correct bytes of DBUS. When writing, the Rambus device will use the lower 3 bits of the address and byte count as a byte mask. When reading, all 64bits are returned and the receiving device will need to implement its own byte masking. The VR4300's pipeline already shifts smaller loads/stores into the correct part of the 64bit double word and implements byte masking for loads, but because 8bit/16bit/32bit operations only result in 32bits of data being transferred across SysAD bus, MI still needs to shift each 32bit word into the correct half of DBus. 

These modes impact all access to the RDRAM address range, not just Rambus registers, but actual memory too. Reads and Writes to other RCP registers and MMIO (like SI, PI or RSP DMEM/IMEM) are unaffected, as that data goes over CBus. 

: '''Normal mode:''' When all special mode bits are disabled, MI maps words onto the DBus as expected. 32bit words are shifted into the upper or low half of the 64bits depending on Addr[2] and any "critical word first" rules.<Br> EBus appears to default to the sign extension of each byte (further testing needed)

: '''Upper mode:''' 32bit transfers are always shifted into the upper half of the 64bit bus.<Br> This mode is labeled as '''"RDRAM register mode"''' in some documentation and is useful for accessing registers on Rambus devices. The Rambus Rreg, Wreg, and WregB commands are hardcoded to ignore the count field of request packets and always do a 32bit transfers. When misinterpreting the RI's 8 byte transfer, the Rambus device always takes the first 4 bytes (which are the upper 32bits of DBus, because RCP is big endian) and ignores the next 4 bytes. Normal mode should produce correct results for registers at even offsets, but you need switch MI into Upper mode to correctly access odd registers.

: '''EBus mode:''' The lower 4 bits of the 32bit word are mapped onto 4 bits of EBus.<Br>In typical operation, EBus is used by RDP and VI to access the extra 9th bit (aka parity/error bit) that RDRAM provides for each byte. This mode allows the CPU to read this extra information back.<Br>Unfortunately this mode doesn't appear to be useful for writing to Antialiased framebuffers, as you can't combine a normal mode write and a EBus mode write without overwriting each other (Future testing required, maybe 64bit transfers work?)

: '''Repeat Mode:''' Writes cause a repeating pattern of '''RepeatCount+1''' bytes (upto 128 bytes) to be written. Reading can cause a hang (further testing needed).<br> First a 64bit value is loaded into the DBus FIFO to be the pattern:

:: {| class="wikitable"
|-
| rowspan="2" | Uncached 64bit write || The 64bit value is used directly 
|-
| <code>reg64=0x01234567_89abcdef -> pattern=0x012345678_9abcdef</code>
|-
| rowspan="2" | Uncached 32bit write || Only the lower 32bits are send over SYSAD, and that is duplicated into both upper and lower halves 
|-
| <code>reg64=0x01234567_89abcdef -> pattern=0x89abcdef_89abcdef</code>
|- 
| rowspan="2" | Uncached 16bit write
|| When writing less than 32bits, the cpu pre-shifts the value and MI sees it as a 32bit write. Normal byte masking is suppressed as it was replaced by RepeatCount.
|-
| <code>reg64=0x01234567_89abcdef, addr[1:0]=0b10 -> pattern=0xcdef0000_cdef0000</code>
|- 
| rowspan="2" |  Uncached 8bit write || ''As Above.'' Notice that some bytes are now unmasked. 
|- 
| <code>reg64=0x01234567_89abcdef, addr[2:0]=0b001 -> pattern=0xabcdef00_abcdef00</code>
|-
| rowspan="2" | Cache writeback || The last 8 bytes of the cacheline are used, everything else is discarded. 
|-
| <code>cacheline="an ascii example" -> pattern=" example example"</code>
|}

: Then MI lies to RI about the transfer count, with '''RepeatCount''' overriding the correct value. causing RI to do <code>RepeatCount[6:3]</code> transfers, with MI repeating the same 64bit value for all transfers.<br> The Rambus device uses '''Addr[2:0]''' and '''RepeatCount[2:0]''' to implement byte masking for the first and last transfers. RI does not correctly implement support for unaligned writes that cross a 64bit boundary, so you end up with <code>RepeatCount[6:3] | RepeatCount[2:0] + Addr[2:0]</code> written, which discards the potential carry out from bit 2 to bit 3. 

: This mode is labeled as '''"Init Mode"''' in some documentation. It's used once during Nintendo's IPL3's RDRAM initialization as a workaround for the default timings after RDRAM reset not being compatible with RI's hardcoded timings. See [[RDRAM#0x02_-_Delay|RDRAM Delay register]] for a detailed explanation.

: Repeat Mode is ideal for fast Memset operations, as you can quickly write a repeating pattern to upto 128 bytes of RAM with just two 32bit uncached writes.<br> For cache-coherency, you do need to invalidate those cache lines, but you can execute the CACHE instructions while MI is finishing the Repeat write with almost no impact to performance.<br> MI repeat is almost as fast as using RSP's DMA, but it will often be faster and more convenient to use MI repeat as the RSP is busy doing other things. 

:: {| class="wikitable"
|+ Memset benchmarks for 1MiB of data.
|-
| 64bit uncached writes || 25.7 ms
|-
| 64bit cached writes || 49.8 ms
|-
| RSP DMA || 2.58 ms
|-
| MI repeat || 3.80 ms (plus 0.20ms with inline CACHE instructions)
|}

: If you are careful, it should be possible to do unaligned memsets too. An uncached byte write can be used to set '''Addr[2:0]''' to any value, and you can adjust '''RepeatCount[6:3]''' to compensate for the missing carry out, so the Rambus device writes the correct number of bytes. 

 
==== <span style="display:none;">0x0430 0004 - MI_VERSION</code> ====
----
{{#invoke:Register table|head|550px|MI_VERSION <code>0x0430 0004</code>}}
{{#invoke:Register table|row|31:24}}
| R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-? || R-?
|-
| colspan="8" | RSP_VERSION[7:0]
{{#invoke:Register table|row|23:16}}
| R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-? || R-?
|-
| colspan="8" | RDP_VERSION[7:0]
{{#invoke:Register table|row|15:8}}
| R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-? || R-?
|-
| colspan="8" | RAC_VERSION[7:0]
{{#invoke:Register table|row|7:0}}
| R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-? || R-?
|-
| colspan="8" | IO_VERSION[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-24 | RSP_VERSION[7:0] | RSP hardware version
| 23-16 | RDP_VERSION[7:0] | RDP hardware version
| 15-8 | RAC_VERSION[7:0] | RAC hardware version
| 7-0 | IO_VERSION[7:0] | IO hardware version
}}
'''Extra Details:'''
: It is not known for certain the full extent of values that can exist here. Most consoles report <code>0x0202_0102</code>, though emulators and other docs seem to mention other similar values such as <code>0x0101_0101</code> or <code>0x0201_0202</code>. iQue retail consoles and early prototypes report <code>0x0202_b0b0</code>. Analogue3D reports <code>0x0303_0303</code>. Testing should be performed on all revisions of the N64 motherboard and development systems. Results will be listed here.

==== <span style="display:none;">0x0430 0008 - MI_INTERRUPT</code> ====
----
{{#invoke:Register table|head|550px|MI_INTERRUPT <code>0x0430 0008</code>}}
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
| U-0 || U-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0
|-
| — || — || DP || PI || VI || AI || SI || SP
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-6 | Undefined | Initialized to <code>0</code>
| 5 | DP | Interrupt flag - Set when the RDP finishes a full sync (requested explicitly via a SYNC_FULL command)
| 4 | PI | Interrupt flag - Set when a PI DMA transfer finishes
| 3 | VI | Interrupt flag - Set when the VI starts processing a specific half-line of the screen (<code>VI_V_CURRENT {{=}}{{=}} VI_V_INTR</code>). Usually, this is configured with <code>VI_V_CURRENT {{=}} 2</code> so that it behaves as a VBlank interrupt.
| 2 | AI | Interrupt flag - Set when the AI begins playing back a new audio buffer (to notify that the next one should be enqueued as soon as possible, to avoid crackings)
| 1 | SI | Interrupt flag - Set when a SI DMA to/from PIF RAM finishes
| 0 | SP | Interrupt flag - Set when the RSP executes a <code>BREAK</code> opcode while <code>SP_STATUS</code> has been configured with the <code>INTERRUPT_ON_BREAK</code> bit; alternatively, it can also be set by explicitly writing the <code>INTERRUPT</code> flag in the <code>SP_STATUS</code> register (by either the CPU or the RSP itself).
}}

==== <span style="display:none;">0x0430 000C - MI_MASK</code> ====
----
{{#invoke:Register table|head|650px|MI_MASK <code>0x0430 000C</code> (Read)}}
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
| U-0 || U-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0
|-
| — || — || DP || PI || VI || AI || SI || SP
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 5 | DP | DP Interrupt Mask
| 4 | PI | PI Interrupt Mask
| 3 | VI | VI Interrupt Mask
| 2 | AI | AI Interrupt Mask
| 1 | SI | SI Interrupt Mask
| 0 | SP | SP Interrupt Mask
}}

{{#invoke:Register table|head|650px|MI_MASK <code>0x0430 000C</code> (Write)}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || W-0 || W-0 || W-0 || W-0
|-
| — || — || — || — || Set DP || Clear DP || Set PI || Clear PI
{{#invoke:Register table|row|7:0}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| Set VI || Clear VI || Set AI || Clear AI || Set SI || Clear SI || Set SP || Clear SP
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 11 | Set DP | Set DP Interrupt Mask
| 10 | Clear DP | Clear DP Interrupt Mask
| 9 | Set PI | Set PI Interrupt Mask
| 8 | Clear PI | Clear PI Interrupt Mask
| 7 | Set VI | Set VI Interrupt Mask
| 6 | Clear VI | Clear VI Interrupt Mask
| 5 | Set AI | Set AI Interrupt Mask
| 4 | Clear AI | Clear AI Interrupt Mask
| 3 | Set SI | Set SI Interrupt Mask
| 2 | Clear SI | Clear SI Interrupt Mask
| 1 | Set SP | Set SP Interrupt Mask
| 0 | Clear SP | Clear SP Interrupt Mask
}}

'''Extra Details:'''

Notice that disabling an interrupt does not prevent the interrupt to be raised in MI_INTERRUPT. It just prevents the interrupt to be signaled to the CPU. If a mask is enabled while the respective interrupt is already set in MI_INTERRUPT, the interrupt is signaled to the CPU right away.

= iQue Player-specific registers =
'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at power on
[x:y] = Specifies bits x to y, inclusively</pre>
==== <span style="display:none;">0x0430 0014 - MI_BB_SECURE_EXCEPTION</code> ====
----
{{#invoke:Register table|head|700px|MI_BB_SECURE_EXCEPTION <code>0x0430 0014</code>}}
{{#invoke:Register table|row|31:24}}
| U-? || U-? || U-? || U-? || U-? || U-? || W-? || W-?
|-
| — || — || — || — || — || — || — || SK RAM Access
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-1 || RW-1
|-
| Module || Button || MI error || PI error || Timer || Application || Boot memory swap || Secure mode
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 25 | Unknown | System software writes to this bit when launching an app or game. (TODO determine the purpose of this bit)
| 24 | SK RAM Access | Setting this bit to 1 enables access to an 0x8000-byte SRAM mapped at 0x1FC40000 outside of secure mode.
| 7 | Module | Secure trap caused by the memory card being removed. (TOVERIFY)
| 6 | Button | Secure trap caused by the power button being pressed. (TOVERIFY: theory is that this cause bit is set when a secure trap is signaled 0.5s after the power button was pressed)
| 5 | MI error | Secure trap caused by an MI error.
| 4 | PI error | Secure trap caused by a PI error.
| 3 | Timer | Secure trap caused by the secure timer.
| 2 | Application | Secure trap caused by an application reading this register outside of secure mode.
| 1 | Boot memory swap | If this is set to 1 the boot ROM is mapped to 0x1FC00000 and Secure Kernel RAM is mapped at 0x1FC20000; this is the state at cold boot. If this is not set the Secure Kernel RAM is mapped at 0x1FC00000 and the boot ROM is mapped at 0x1FC20000.
| 0 | Secure mode | Secure Kernel writes 0 here to exit secure mode. This is effective immediately, all future memory accesses that miss the CPU cache will be unable to access secure mode resources. Whenever this register is written to without the intention to exit secure mode, a 1 must be re-written here.
}}

'''Extra Details:'''
: Secure traps are implemented as an NMI to the CPU and are vectored to 0xBFC00000, this register is then used by the Secure Kernel as a Cause register to determine the reason for the secure trap and the relevant handler is entered.
: Reading (and possibly writing, TOVERIFY) this register from non-secure mode (i.e. from a game or application) causes a secure trap with the Application bit set in this register. This mechanism is how SKCs ([[Secure Kernel Calls]]) are implemented; the application sets up the required CPU registers for the call before reading this register to trigger the Application trap.

==== <span style="display:none;">0x0430 002C - MI_BB_RANDOM</code> ====
----
{{#invoke:Register table|head|700px|MI_BB_RANDOM <code>0x0430 002C</code>}}
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
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || R-?
|-
| — || — || — || — || — || — || — || Random
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 0 | Random | Single bit hardware-generated random value. Accumulating bits from this register can produce larger random numbers that are (theoretically) suitable for cryptographic purposes. The Secure Kernel uses this for gathering entropy as part of generating new cryptographic keys.
}}

==== <span style="display:none;">0x0430 0038 - MI_BB_INTERRUPT</code> ====
----
{{#invoke:Register table|head|800px|MI_BB_INTERRUPT <code>0x0430 0038</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || R-0 || R-0
|-
| — || — || — || — || — || — || MD_STATE || BTN_STATE
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || RW-0 || R-0 || R-0 || R-0 || R-0 || R-0
|-
| — || — || MD || BTN || USB1 || USB0 || PI_ERR || IDE
{{#invoke:Register table|row|7:0}}
| R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0
|-
| AES || FLASH || DP || PI || VI || AI || SI || SP
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 25 | MD_STATE | If 0, indicates that the memory card is present. If 1, indicates that the memory card is currently removed.
| 24 | BTN_STATE | If 0, indicates that the power button is not currently held. If 1, indicates that the power button is currently held.
| 13 | MD | Interrupt flag - Set when the memory card is removed from the console. Writing to this bit clears the interrupt.
| 12 | BTN | Interrupt flag - Set when the power button is pressed. This flag is not typically useful as this triggers an Int2 interrupt rather than Int1 like the other Que-specific interrupts.
| 11 | USB1 | Interrupt flag - Set by USB events on connector 1 (TOVERIFY what kind of events?)
| 10 | USB0 | Interrupt flag - Set by USB events on connector 0 (TOVERIFY what kind of events?)
| 9 | PI_ERR | Interrupt flag - Set on "PI Errors"? (TOVERIFY what sort of errors?)
| 8 | IDE | Interrupt flag - IDE (TODO What is IDE? Only the name is known from some library debug info)
| 7 | AES | Interrupt flag - Set when an AES decryption operation completes
| 6 | FLASH | Interrupt flag - Set when a NAND command completes
| 5 | DP | Interrupt flag - Same as N64 (see MI_INTERRUPT)
| 4 | PI | Interrupt flag - Same as N64 (see MI_INTERRUPT)
| 3 | VI | Interrupt flag - Same as N64 (see MI_INTERRUPT)
| 2 | AI | Interrupt flag - Same as N64 (see MI_INTERRUPT)
| 1 | SI | Interrupt flag - Same as N64 (see MI_INTERRUPT)
| 0 | SP | Interrupt flag - Same as N64 (see MI_INTERRUPT)
}}

'''Extra Details:'''

The additional iQue-specific interrupts in bits 6-11 and bit 13 raise Int1 in the COP0 Cause register rather than Int0 like the N64's RCP interrupts. On N64 Int1 was attached to the Cartridge and Disk Drive ports. Bit 12 (power button) raises Int2/PreNMI, followed by a secure trap 0.5s later.

==== <span style="display:none;">0x0430 003C - MI_BB_MASK</code> ====
----
{{#invoke:Register table|head|650px|MI_BB_MASK <code>0x0430 003C</code> (Read)}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || R-0 || R-0 || R-0 || R-0|| R-0 || R-0
|-
| — || — || MD || BTN || USB1 || USB0 || PI_ERR || IDE
{{#invoke:Register table|row|7:0}}
| R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0 || R-0
|-
| AES || FLASH || DP || PI || VI || AI || SI || SP
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 13 | MD | MD Interrupt Mask
| 12 | BTN | BTN Interrupt Mask
| 11 | USB1 | USB1 Interrupt Mask
| 10 | USB0 | USB0 Interrupt Mask
| 9 | PI_ERR | PI_ERR Interrupt Mask
| 8 | IDE | IDE Interrupt Mask
| 7 | AES | AES Interrupt Mask
| 6 | FLASH | FLASH Interrupt Mask
| 5 | DP | DP Interrupt Mask
| 4 | PI | PI Interrupt Mask
| 3 | VI | VI Interrupt Mask
| 2 | AI | AI Interrupt Mask
| 1 | SI | SI Interrupt Mask
| 0 | SP | SP Interrupt Mask
}}

{{#invoke:Register table|head|650px|MI_BB_MASK <code>0x0430 003C</code> (Write)}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || W-0 || W-0 || W-0 || W-0
|-
| — || — || — || — || Set MD || Clear MD || Set BTN || Clear BTN
{{#invoke:Register table|row|23:16}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| Set USB1 || Clear USB1 || Set USB0 || Clear USB0 || Set PI_ERR || Clear PI_ERR || Set IDE || Clear IDE
{{#invoke:Register table|row|15:8}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| Set AES || Clear AES || Set FLASH || Clear FLASH || Set DP || Clear DP || Set PI || Clear PI
{{#invoke:Register table|row|7:0}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| Set VI || Clear VI || Set AI || Clear AI || Set SI || Clear SI || Set SP || Clear SP
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 27 | Set MD | Set MD Interrupt Mask
| 26 | Clear MD | Clear MD Interrupt Mask
| 25 | Set BTN | Set BTN Interrupt Mask
| 24 | Clear BTN | Clear BTN Interrupt Mask
| 23 | Set USB1 | Set USB1 Interrupt Mask
| 22 | Clear USB1 | Clear USB1 Interrupt Mask
| 21 | Set USB0 | Set USB0 Interrupt Mask
| 20 | Clear USB0 | Clear USB0 Interrupt Mask
| 19 | Set PI_ERR | Set PI_ERR Interrupt Mask
| 18 | Clear PI_ERR | Clear PI_ERR Interrupt Mask
| 17 | Set IDE | Set IDE Interrupt Mask
| 16 | Clear IDE | Clear IDE Interrupt Mask
| 15 | Set AES | Set AES Interrupt Mask
| 14 | Clear AES | Clear AES Interrupt Mask
| 13 | Set FLASH | Set FLASH Interrupt Mask
| 12 | Clear FLASH | Clear FLASH Interrupt Mask
| 11 | Set DP | Set DP Interrupt Mask
| 10 | Clear DP | Clear DP Interrupt Mask
| 9 | Set PI | Set PI Interrupt Mask
| 8 | Clear PI | Clear PI Interrupt Mask
| 7 | Set VI | Set VI Interrupt Mask
| 6 | Clear VI | Clear VI Interrupt Mask
| 5 | Set AI | Set AI Interrupt Mask
| 4 | Clear AI | Clear AI Interrupt Mask
| 3 | Set SI | Set SI Interrupt Mask
| 2 | Clear SI | Clear SI Interrupt Mask
| 1 | Set SP | Set SP Interrupt Mask
| 0 | Clear SP | Clear SP Interrupt Mask
}}

'''Extra Details:'''

Notice that disabling an interrupt does not prevent the interrupt to be raised in MI_BB_INTERRUPT. It just prevents the interrupt to be signaled to the CPU. If a mask is enabled while the respective interrupt is already set in MI_BB_INTERRUPT, the interrupt is signaled to the CPU right away.

The interrupts shared with N64 are mirrors of the MI_MASK state. Updating one register updates the other automatically.

Note that if the BTN interrupt is disabled the NMI triggered by the button is also disabled, rather than just the Int2/PreNMI interrupt.
