<!--
  Source: https://n64brew.dev/wiki/Reality_Signal_Processor/CPU_Core
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

== Scalar unit (SU) ==
The scalar is the half of the RSP core that is similar to a standard MIPS R4000 32-bit CPU. It has 32 32-bit registers (conventionally called <code>r0</code>-<code>r31</code>) and implement most standard opcodes. This page does not describe the whole scalar unit as standard MIPS documentation suffices, but it highlights the main difference.

=== Missing opcodes ===
The following opcodes are not implemented by RSP:

* '''Multiplication units.''' RSP does not have a multiplication unit so there is no MULT, MULTU, DIV, DIVU, MFHI, MFLO, MTHI, MTLO.
* '''64-bit instructions.''' RSP only has 32-bit scalar registers in SU, so there is no 64-bit opcodes (the ones starting with D such as DADDIU, DSRL, etc.) nor 64-bit memory accesses such as LD, SD, LDL, SDL.
* '''No opcodes for misaligned memory accesses.''' All memory accesses to DMEM can be correctly performed also to misaligned addresses, using the standard opcodes like LW / SW or LH / LHU / SH, so there is no LWL, LWR, SWL, SWR.
* '''No traps or exceptions.''' RSP does not implement any form of interrupt or exception handling, so there is no SYSCALL nor trap instructions (TGE, TLT, etc.). BREAK is available but it has a special behavior (see below).
* '''No support for likely branches.''' The "likely" variant of all branches is not supported. The missing opcodes are the ones ending with L (such as BEQL, BLEZL, etc.)

=== Memory access ===
RSP is a harvard architecture. All opcodes are fetched from IMEM (4KB) and all data is access in DMEM (4KB). 

The PC register is 12-bit. All higher address bits in branch / call instructions are thus ignored. When PC reaches the last opcode (at 0xFFC), execution continues to the first opcode in IMEM (PC wraps to 0x000).

All accesses to DMEM are performed using the lowest 12 bits of the address calculated by the load/store instruction (higher bits are ignored). Moreover, contrary to standard MIPS architecture, the RSP can correctly perform misaligned memory accesses (eg: it is possibly to fetch a 32-bit word at address 0x001, that will contain the 4 bytes at 0x1-0x5). Standard MIPS architecture allows to do misaligned addresses only using the LWL/LWR or SWL/SWR couples, which are not required on the RSP.

== Vector Unit (VU) ==
The VU is the internal unit of the RSP CPU core that is able to perform fixed-point SIMD calculations. It is a proprietary design which does not follow any standard specification. Its opcodes and registers are exposed to the core via the COP2 interface. 

=== Vector registers and glossary ===
VU contains 32 128-bit SIMD registers, each organized in 8 lanes of 16-bit each one. Most VU opcodes perform the same operation in parallel on each of the 8 lanes. The arrangement is thus similar to x86 SSE2 registers in EPI16 format.

The vector registers array is called <code>VPR</code> in this document, so <code>VPR[4]</code> refers to the fifth register (usually called <code>v4</code> in assembly). When referring to specific portions of the register, we use the following convention:

* <code>VPR[vt][4..7]</code> refers to byte indices, that is bytes from 4 to 7, counting from the higher part of the register (in big-endian order).
* <code>VPR[vt]<4..7></code> refers to specific lane indices, that is lanes from 4 to 7 counting from the higher part of the register (in big-endian order).
* Within each lane, <code>VPR[vt]<2>(3..0)</code> refers to inclusive bit ranges. Notice that bits are counted as usual in little-endian order (bit 0 is the lowest, bit 15 is the highest), and thus they are written as <code>(high..low)</code>.

Ranges are specified using the <code>beg..end</code> inclusive notation (that is, both <code>beg</code> and <code>end</code> are part of the range).

The concatenation of disjoint ranges is written with a <code>,</code>, for instance: <code>[0..3,8..11]</code> means 8 bytes formed by concatenating 4 bytes starting at 0 with 4 bytes starting at 8.

Vector lanes are usually interpreted as a fixed point number. As a homebrew programmer, it is useful to understand the meaning of each opcode and its correct usage while writing code, which goes beyond the exact hardware description of how bits are shuffled around. To refer to a fixed point number, we use the syntax <code>S1.15</code> where "S" means "signed" (while "U" is "unsigned"), "1" is the number of bits for the integral part, and "15" are the number of bits for the fractional part.

=== Accumulator ===
The RSP contains a 8-lane SIMD accumulator, that is used implicitly by multiplication opcodes. Each of the 8 lanes is 48-bits wide, that allows to accumulate intermediate results of calculations without the loss of precision that would incur when storing them into a 16-bit lane in a vector register.

It is possible to extract the contents of the accumulator through the VSAR opcode; one call to this opcode can extract a 16-bit portion of each lane and store it into the specified vector register. The three portions are conventionally called <code>ACCUM_LO</code> (bits 15..0 of each lane), <code>ACCUM_MD</code> (bits 31..16 of each lane), and <code>ACCUM_HI</code> (bits 47..32 of each lane).

If you exclude the VSAR instruction that cuts the accumulator piecewise for extracting it, it is better to think of it a single register where each lane is 48-bits wide.

=== Control registers ===
The VU contains 3 16-bit control registers: VCC, VCO, VCE. 

These registers are used as flag registers by several opcodes. As with most flags, even though they have a general meaning that is generally valid, they tend to also be used in some mind-twisting way to obtain the desired result. It doesn't really make sense to try to describe them at the general level and instead each instruction will explain if/how it uses or modifies the control registers.

To read/write the contents of the control registers, the <code>ctc2</code> / <code>cfc2</code> instructions can be used.

=== Clamping ===
Multiplication opcodes perform a clamping step when extracting the accumulator into a vector register. Notice that each lane of the accumulator is always treated as a ''signed'' 48-bit number.

This is the pseudo-code for signed clamping (no surprises):
 <code>function clamp_signed(accum)
     if accum < -32768  => return -32768
     if accum > 32767   => return 32767
     return accum</code>
The returned value is thus always within the signed 16-bit range.

This is the pseudo-code for unsigned clamping:
 <code>function clamp_unsigned(accum)
     if accum < 0       => return 0
     if accum > 32767   => return 65535
     return accum</code>
Notice that in unsigned clamping, the saturating threshold is 15-bit, but the saturated value is 16-bit.

=== Element field ===
Most VU instructions have a 3-register format with an additional modifier called "element field". For instance (using GNU assembly syntax):<syntaxhighlight lang="asm">
opcode v0, v1, v2,e(7)

</syntaxhighlight><code>e(7)</code> is the "element modifier". Normally (and especially in GNU syntax, which is more orthogonal and uniform), it refers to a specific lane of the third register, which is why it is common to format it without a leading whitespace. In this example, it "selects" lane 7 of register <code>v2</code>. The exact meaning of the element modifier varies for different instruction groups, and also the way it is assembled changes wildly. Pay attention to the description of each instruction group to check what the element modifier means and how it is encoded in the opcode.

=== Broadcast modifier ===
One of the most common uses of the element field is the broadcast modifier. This modifier is used by computational instructions and select instructions and allows to "broadcast" (duplicate) one or more lanes to other lanes, just for the purpose of the current opcode. For instance:<syntaxhighlight lang="asm">
vaddc $v01, $v04,e(1)
</syntaxhighlight><code>e(1)</code> is the broadcast modifier. Normally, the instruction would add the two registers lane by lane; with the modifier, the second lane (index 1) of <code>$v04</code> is added to all lanes of <code>$v01</code>.

The modifier is stored in the <code>element</code> field of the opcode
{| class="wikitable"
!<code>element</code>
!GNU syntax
!SGI syntax
!Lanes being accessed
!Description
|-
|0
|
|
|0,1,2,3,4,5,6,7
|Normal register access (no broadcast)
|-
|1
|
|
|0,1,2,3,4,5,6,7
|Normal register access (no broadcast)
|-
|2
|<code>e(0q)</code>
|<code>[0q]</code>
|0,0,2,2,4,4,6,6
|Broadcast 4 of 8 lanes
|-
|3
|<code>e(1q)</code>
|<code>[1q]</code>
|1,1,3,3,5,5,7,7
|Broadcast 4 of 8 lanes
|-
|4
|<code>e(0h)</code>
|<code>[0h]</code>
|0,0,0,0,4,4,4,4
|Broadcast 2 of 8 lanes
|-
|5
|<code>e(1h)</code>
|<code>[1h]</code>
|1,1,1,1,5,5,5,5
|Broadcast 2 of 8 lanes
|-
|6
|<code>e(2h)</code>
|<code>[2h]</code>
|2,2,2,2,6,6,6,6
|Broadcast 2 of 8 lanes
|-
|7
|<code>e(3h)</code>
|<code>[3h]</code>
|3,3,3,3,7,7,7,7
|Broadcast 2 of 8 lanes
|-
|8
|<code>e(0)</code>
|<code>[0]</code>
|0,0,0,0,0,0,0,0
|Broadcast single lane
|-
|9
|<code>e(1)</code>
|<code>[1]</code>
|1,1,1,1,1,1,1,1
|Broadcast single lane
|-
|10
|<code>e(2)</code>
|<code>[2]</code>
|2,2,2,2,2,2,2,2
|Broadcast single lane
|-
|11
|<code>e(3)</code>
|<code>[3]</code>
|3,3,3,3,3,3,3,3
|Broadcast single lane
|-
|12
|<code>e(4)</code>
|<code>[4]</code>
|4,4,4,4,4,4,4,4
|Broadcast single lane
|-
|13
|<code>e(5)</code>
|<code>[5]</code>
|5,5,5,5,5,5,5,5
|Broadcast single lane
|-
|14
|<code>e(6)</code>
|<code>[6]</code>
|6,6,6,6,6,6,6,6
|Broadcast single lane
|-
|15
|<code>e(7)</code>
|<code>[7]</code>
|7,7,7,7,7,7,7,7
|Broadcast single lane
|}

=== Instructions overview ===

==== Loads and stores ====
{| class="wikitable"
!31..26
!25..21
!20..16
!15..11
!10..7
!6..0
|-
|<code>LWC2</code> or <code>SWC2</code>
|<code>base</code>
|<code>vt</code>
|<code>opcode</code>
|<code>element</code>
|<code>offset</code>
|}
The instructions perform a load/store from DMEM into/from a vector register.

* <code>base</code> is the index of a scalar register used as base for the memory access
* <code>offset</code> is a signed offset added to the value of the base register (with some scaling, depending on the actual instruction).
* <code>vt</code> is the vector register.
* <code>element</code> is used to index a specific byte/word within the vector register, usually specifying the first element affected by the operation (thus allows to access sub-portions of the vector register).

{| class="wikitable"
|+List of all loads and stores opcodes
!Group
!Opcode
!Instruction
!Description
|-
| rowspan="4" |Scalar
|0x00
|<code>lbv</code> / <code>sbv</code>
|Load / Store 1 byte into/from a VPR
|-
|0x01
|<code>lsv</code> / <code>ssv</code>
|Load / Store 2 bytes into/from a VPR
|-
|0x02
|<code>llv</code> / <code>slv</code>
|Load / Store 4 bytes into/from a VPR
|-
|0x03
|<code>ldv</code> / <code>sdv</code>
|Load / Store 8 bytes into/from a VPR
|-
| rowspan="4" |128-bit
|0x04
|<code>lqv</code>
|Load (up to) 16 bytes into a VPR, left-aligned
|-
|0x05
|<code>lrv</code>
|Load (up to) 16 bytes into a VPR, right-aligned
|-
|0x04
|<code>sqv</code>
|Store (up to) 16 bytes from a VPR, left-aligned
|-
|0x05
|<code>srv</code>
|Store (up to) 16 bytes from a VPR, right-aligned
|-
| rowspan="4" |8-bit packed
|0x06
|<code>lpv</code> / <code>spv</code>
|Load / store 8 8-bit signed values into a VPR
|-
|0x07
|<code>luv</code> / <code>suv</code>
|Load / store 8 8-bit unsigned values into a VPR
|-
|0x08
|<code>lhv</code> / <code>shv</code>
|Load / store 8 8-bit unsigned values into VPR, accessing every other byte in memory
|-
|0x09
|<code>lfv</code> / <code>sfv</code>
|Load / store 4 8-bit unsigned values into VPR, accessing every fourth bytes in memory
|-
| rowspan="3" |Transpose
|0x01
|<code>swv</code>
|
|-
|0x0B
|<code>ltv</code>
|Load 8 lanes from 8 GPRs into a VPR
|-
|0x0B
|<code>stv</code>
|Store 8 lanes of a VPR into 8 GPRs
|}

==== Single-lane instructions ====
{| class="wikitable"
!31..26
!25
!24..21
!20..16
!15..11
!10..6
!5..0
|-
|<code>COP2</code>
|1
|<code>vt_elem</code>
|<code>vt</code>
|<code>vd_elem</code>
|<code>vd</code>
|<code>opcode</code>
|}
Single-lane instructions are an instruction group that perform operations on a single lange of a single input register (<code>VT<se></code>), and store the result into a single lane of a single output register (<code>VD<de></code>).

Example syntax:<syntaxhighlight lang="asm">
vmov $v01, e(4), $v05, e(6)
</syntaxhighlight>In this example, the value in lane <code>$v05<6></code> is moved to lane <code>$v01<4></code>. In the assembly syntax, the [[Reality Signal Processor/CPU Core#Broadcast modifiers|broadcast modifier syntax]] is used, but no actual broadcast is performed, as the instructions operate on the single specified lane. Only the single-lane broadcast modifiers (<code>e(0)</code> ... <code>e(7)</code>) are supported.+

In the opcode, the fields <code>vt_elem</code> and <code>vd_elem</code> are used to compute <code>se</code> and <code>de</code> that is to specify which lane, respectively of the input and output register, is affected.

<code>vd_elem</code> is 5 bits long (range 0..31); the highest bits are always ignored, and the destination lane <code>de</code> is simply <code>vd_elem(2..0)</code>.

<code>vt_elem</code> is 4 bits long (range 0..15). When <code>vt_elem(3)</code> is 1, <code>vt_elem(2..0)</code> is actually used as source lane <code>se</code>, as expected. When <code>vt_elem(3)</code> is 0, a hardware bug is triggered and portions of the lower bits of <code>vt_elem</code> are replaced with portion of the bits of <code>vd_elem</code> while computing <code>se</code>. Specifically, all bits in <code>vt_elem</code> from the topmost set bit and higher are replaced with the same-position bits in <code>vd_elem</code>. Notice that this behaviour is actually consistent with what happens when <code>vt_elem(3)</code> is 1, which means that there is no need to think of it as a special-case. Pseudo-code:
 <code>de(2..0) = vd_elem(2..0)
 msb = highest_set_bit(vt_elem)
 se(2..0) = vd_elem(2..msb) || vt_elem(msb-1..0)</code>
{| class="wikitable"
|+Single-lane instructions
!Opcode
!Instruction
!Description
|-
|0x33
|<code>vmov</code>
|Copy one lane of a VPR into another VPR
|-
|0x30
|<code>vrcp</code>
|Compute the 32-bit reciprocal of a 16-bit fixed point
|-
|0x34
|<code>vrsq</code>
|Compute the 32-bit reciprocal square root of a 16-bit fixed point
|-
|0x32
|<code>vrcph</code>
|Extract the higher 16-bit of the result of a previous VRCP
|-
|0x36
|<code>vrsqh</code>
|Extract the higher 16-bit of the result of a previous VRSQ
|-
|0x31
|<code>vrcpl</code>
|Compute the 32-bit reciprocal of a 32-bit fixed point
|-
|0x35
|<code>vrsql</code>
|Compute the 32-bit reciprocal square root of a 32-bit fixed point
|-
|0x37
|<code>vnop</code>
|No operation (?)
|-
|0x3F
|<code>vnull</code>
|No operation (?)
|}

==== Computational instructions ====
{| class="wikitable"
!31..26
!25
!24..21
!20..16
!15..11
!10..6
!5..0
|-
|<code>COP2</code>
|1
|<code>element</code>
|<code>vt</code>
|<code>vs</code>
|<code>vd</code>
|<code>opcode</code>
|}
Instructions have this general format:
 <code>VINSN vd, vs, vt,e(…)</code>
where <code>e(…)</code> is the [[Reality Signal Processor/CPU Core#Broadcast modifier|broadcast modifier]] (as found in other SIMD architectures), that modifies the access to <code>vt</code> duplicating some lanes and hiding others.

This is the list of opcodes in this group.
{| class="wikitable"
!Opcode
!Instruction
!Description
|-
|0x00
|<code>vmulf</code>
|Vector multiply S1.15 * S1.15, with rounding and signed clamping
|-
|0x01
|<code>vmulu</code>
|Vector multiply S1.15 * S1.15 with rounding and unsigned clamping
|-
|0x04
|<code>vmudl</code>
|Vector multiply U0.16 * U0.16 with signed clamping
|-
|0x05
|<code>vmudm</code>
|Vector multiply S0.16 * U0.16 with signed clamping 
|-
|0x06
|<code>vmudn</code>
|Vector multiply U0.16 * S0.16 with signed clamping
|-
|0x07
|<code>vmudh</code>
|Vector multiply S0.16 * S0.16 with signed clamping
|-
|0x08
|<code>vmacf</code>
|Like VMULF, but also add the result to the accumulator
|-
|0x09
|<code>vmacu</code>
|Like VMULU, but also add the result to the accumulator
|-
|0x0C
|<code>vmadl</code>
|Like VMUDL, but also add the result to the accumulator
|-
|0x0D
|<code>vmadm</code>
|Like VMUDM, but also add the result to the accumulator
|-
|0x0E
|<code>vmadn</code>
|Like VMUDN, but also add the result to the accumulator
|-
|0x0F
|<code>vmadh</code>
|Like VMUDH, but also add the result to the accumulator
|-
|0x10
|<code>vadd</code>
|Vector add with carry
|-
|0x13
|<code>vabs</code>
|Vector absolute value
|-
|0x14
|<code>vaddc</code>
|Vector add writing overflow into carry
|-
|0x1D
|<code>vsar</code>
|Read a portion of the accumulator into a VPR
|-
|0x28
|<code>vand</code>
|Vector bitwise and (<code>a & b</code>)
|-
|0x29
|<code>vnand</code>
|Vector bitwise nand (<code>~(a & b)</code>)
|-
|0x2A
|<code>vor</code>
|Vector bitwise or (<code><nowiki>a | b</nowiki></code>)
|-
|0x2B
|<code>vnor</code>
|Vector bitwise nor (<code><nowiki>~(a | b)</nowiki></code>)
|-
|0x2C
|<code>vxor</code>
|Vector bitwise xor (<code>a ^ b</code>)
|-
|0x2D
|<code>vnxor</code>
|Vector bitwise nxor (<code>~(a ^ b)</code>)
|}

==== Select instructions ====
{| class="wikitable"
!31..26
!25
!24..21
!20..16
!15..11
!10..6
!5..0
|-
|<code>COP2</code>
|1
|<code>element</code>
|<code>vt</code>
|<code>vs</code>
|<code>vd</code>
|<code>opcode</code>
|}
Instructions have this general format:
 <code>VINSN vd, vs, vt, e(…)</code>
where <code>e(…)</code> is the [[Reality Signal Processor/CPU Core#Broadcast modifier|broadcast modifier]] (as found in other SIMD architectures), that modifies the access to <code>vt</code> duplicating some lanes and hiding others. See the Computational instructions section for details.

This is the list of opcodes in this group:
{| class="wikitable"
!Opcode
!Instruction
!Description
|-
|0x20
|<code>vlt</code>
|Select the lower value between two VPR
|-
|0x21
|<code>veq</code>
|Compare two VPR to check if they are equal
|-
|0x22
|<code>vne</code>
|Compare two VPR to check if they are different
|-
|0x23
|<code>vge</code>
|Select the greater or equal value between two VPR
|-
|0x24
|<code>vcl</code>
|Clip a VPR against two bounds (lower 16-bits)
|-
|0x25
|<code>vch</code>
|Clip a VPR against two bounds (higher 16-bits)
|-
|0x26
|<code>vcr</code>
|Clip a VPR against a pow-2 bound
|-
|0x27
|<code>vmrg</code>
|Merge two VPR selecting each lane according to flags
|}

==== VU/SU Moves ====
{| class="wikitable"
!31..26
!25..21
!20..16
!15..11
!10..7
!6..0
|-
|<code>COP2</code>
|<code>opcode</code>
|<code>rt</code>
|<code>vs</code>
|<code>vs_elem</code>
|0
|}
These are the standard MIPS opcodes for moving data in/out the coprocessor registers.
{| class="wikitable"
!<code>opcode</code>
!Instruction
!Description
|-
|0x0
|<code>mfc2</code>
|Copy a lane of a VPR into a GPR
|-
|0x2
|<code>cfc2</code>
|Copy a VU control register into a GPR
|-
|0x4
|<code>mtc2</code>
|Copy a GPR into a lane of a VPR
|-
|0x6
|<code>ctc2</code>
|Copy a GPR into a VU control register
|}
Vector moves follow the same format as standard MIPS coprocessor moves, but use part of the lower 11 bits (which are normally unused) to specify the element field, selecting which lane of the VPR is accessed. Notice that, <code>vs_elem</code> in this case is not a broadcast modifier: it specifies a byte offset (not a lane index!), so to copy a lane, <code>lane*2</code> must be specified.

This is an example using GNU syntax:<syntaxhighlight lang="asm">
mtc2 a1, $v04,e(4)
</syntaxhighlight>This example will copy the lower 16 bits of GPR <code>a1</code> into the fifth lane of <code>$v04</code>. This opcode is assembled with <code>vs_elem = 8</code>, as explained above.

<code>mtc2</code> moves the lower 16 bits of the general purpose register <code>rt</code> to the bytes <code>VS[vs_elem+1..vs_elem]</code>. If <code>vs_elem</code> is 15, only <code>VS[vs_elem]</code> is written (with <code>rt[15..8]</code>). 

<code>mfc2</code> moves the 2 bytes <code>VS[vs_elem+1..vs_elem]</code> to GPR <code>rt</code>, sign extending the 16 bits value to 32 bits. If <code>vs_elem</code> is 15, the lower byte is taken from byte 0 of the register (that is, it wraps around).

<code>ctc2</code> moves the lower 16 bits of GPR <code>rt</code> into the control register specified by <code>vs</code>, while <code>cfc2</code> does the reverse, moving the control register specified by <code>vs</code> into GPR <code>rt</code>, sign extending to 32 bits. Note that both <code>ctc2</code> and <code>cfc2</code> ignore the <code>vs_elem</code> field. For these instructions, the control register is specified as follows:
{| class="wikitable"
!<code>vs</code>
!Register
|-
|0
|<code>VCO</code>
|-
|1
|<code>VCC</code>
|-
|2
|<code>VCE</code>
|}

=== Instruction details ===

==== Scalar loads: LBV, LSV, LLV, LDV ====
{| class="wikitable"
!31..26
!25..21
!20..16
!15..11
!10..7
!6..0
|-
|<code>LWC2</code>
|<code>base</code>
|<code>vt</code>
|<code>opcode</code>
|<code>element</code>
|<code>offset</code>
|}

===== Assembly =====
<syntaxhighlight lang="asm">
lsv $v01,e(2), 0,s0    ; Load the 16-bit word at s0 into the third lane of $v01
lbv $v04,8, 0,s1       ; Load the 8-bit word at s1 into the 9th byte of $v04 (MSB of lane 4)
</syntaxhighlight>Notice that it is possible to specify the lane syntax for the <code>element</code> field to refer to a specific lane, but if the access is made using <code>llv</code> or <code>ldv</code> (4 or 8 bytes), it will overflow into the following lanes.

===== Pseudo-code =====
<syntaxhighlight lang="c">
addr = GPR[base] + offset * access_size
data = DMEM[addr..addr+access_size-1]
VPR[vt][element..element+access_size-1] = data


</syntaxhighlight>

===== Description =====
These instructions load a scalar value (1, 2, 4, or 8 bytes) from DMEM into a VPR. Loads affect only a portion of the vector register (which is 128-bit); other bytes in the register are not modified.

The address in DMEM where the value is fetched is computed as <code>GPR[base] + (offset * access_size)</code>, where <code>access_size</code> is the number of bytes being accessed (eg: 4 for <code>llv</code>). The address can be misaligned: despite how memory accesses usually work on MIPS, these instructions perform unaligned memory accesses.

The part of the vector register being accessed is <code>VPR[vt][element..element+access_size]</code>, that is <code>element</code> selects the first accessed byte within the vector register. When <code>element+access_size</code> is bigger than 15, fewer bytes are processed (eg: <code>llv</code> with <code>element=13</code> only loads 3 byte from memory into <code>VPR[vt][13..15]</code>).

===== Usage =====
These instructions are seldom used. Normally, it is better to structure RSP code to work across full vectors to maximize parallelism. Input data should already be provided in vectorized format by the CPU, so that it is possible to use a vector load (<code>lqv</code>, in case the input is made of 16-bit data) or a packed load (<code>luv</code>/<code>lpv</code>, in case the input is made of 8-bit data). Consider also using <code>mtc2</code> to load a 16-bit value into a lane of a VPR when the value is available in a GPR.

A possible use-case for these instructions is to reverse the order of the lanes. For instance, in audio codecs, windowing algorithms often work combining sequences audio samples with other sequences in reverse order. RSP does not have an instruction to reverse the order of the lanes, so in that case it might be necessary to manually reverse the lanes while loading using <code>lsv</code>:<syntaxhighlight lang="asm">
lqv $v00, 0,s0         ; Load 8 16-bit samples from DMEM at address s0
lsv $v01,e(7),  0,s1   ; Load 8 16-bit samples from DMEM at address s1 in reverse order
lsv $v01,e(6),  2,s1
lsv $v01,e(5),  4,s1
lsv $v01,e(4),  6,s1
lsv $v01,e(3),  8,s1
lsv $v01,e(2), 10,s1
lsv $v01,e(1), 12,s1
lsv $v01,e(0), 14,s1
</syntaxhighlight>

==== Scalar stores: SBV, SSV, SLV, SDV ====
{| class="wikitable"
!31..26
!25..21
!20..16
!15..11
!10..7
!6..0
|-
|<code>SWC2</code>
|<code>base</code>
|<code>vt</code>
|<code>opcode</code>
|<code>element</code>
|<code>offset</code>
|}

===== Assembly =====
<syntaxhighlight lang="asm">
ssv $v01,e(2), 0,s0    ; Store the 16-bit word in the third lane of $v01 into DMEM at address s0
sbv $v04,8, 0,s1       ; Store the 8-bit word in the 9th byte of $v04 (MSB of lane 4) into DMEM at address s1
</syntaxhighlight>Notice that it is possible to specify the lane syntax for the <code>element</code> field to refer to a specific lane, but if the access is made using <code>slv</code> or <code>sdv</code> (4 or 8 bytes), it will overflow into the following lanes.

===== Pseudo-code =====
<syntaxhighlight lang="c">
addr = GPR[base] + offset * access_size
data = VPR[vt][element..element+access_size-1]
DMEM[addr..addr+access_size-1] = data

</syntaxhighlight>

===== Description =====
These instructions store a scalar value (1, 2, 4, or 8 bytes) from a VPR into DMEM.

The address in DMEM where the value will be stored is computed as <code>GPR[base] + (offset * access_size)</code>, where <code>access_size</code> is the number of bytes being accessed (eg: 4 for <code>SLV</code>). The address can be misaligned: despite how memory accesses usually work on MIPS, these instructions perform unaligned memory accesses.

The part of the vector register being accessed is <code>VPR[vt][element..element+access_size]</code>, that is <code>element</code> selects the first accessed byte within the vector register. When <code>element+access_size</code> is bigger than 15, the element access wraps within the vector and a full-size store is always performed (eg: <code>slv</code> with <code>element=15</code> stores <code>VPR[vt][15,0..2]</code> into memory, for a total of 4 bytes).

===== Usage =====
These instructions are seldom used. Normally, it is better to structure RSP code to work across full vectors to maximize parallelism. Data flow between RSP and VR4300 should be structured in vectorized format, so that it is possible to use a vector store (<code>sqv</code>, in case the output is made of 16-bit data) or a packed load (<code>suv</code>/<code>spv</code>, in case the output is made of 8-bit data). Consider also using <code>mfc2</code> to store a 16-bit value from the lane of a VPR into a GPR.

See [[Reality Signal Processor/CPU Core#Scalar loads: LBV, LSV, LLV, LDV|scalar loads]] for an example of a use-case (reversing a vector) that can be implemented also via <code>ssv</code>.

==== 128-bit vector loads: LQV, LRV ====
{| class="wikitable"
!31..26
!25..21
!20..16
!15..11
!10..7
!6..0
|-
|<code>LWC2</code>
|<code>base</code>
|<code>vt</code>
|<code>opcode</code>
|<code>element</code>
|<code>offset</code>
|}
{| class="wikitable"
!Insn
!<code>opcode</code>
!Desc
|-
|<code>LQV</code>
|0x04
|load (up to) 16 bytes into vector, left-aligned
|-
|<code>LRV</code>
|0x05
|load (up to) 16 bytes into vector, right-aligned
|}

===== Assembly =====
<syntaxhighlight lang="asm">
// Standard 128-bit load from DMEM aligned address s0 into $v08
lqv $v08, 0,s0

// Loading a misaligned 128-bit vector from DMEM
// (a0 is 128-bit aligned in this example)
lqv $v00, 0x08,a0    // read bytes 0x08(a0) - 0x0F(a0) into left part of the vector (VPR[vt][0..7])
lrv $v00, 0x18,a0    // read bytes 0x10(a0) - 0x17(a0) into right part of the vector (VPR[vt][8..15])

// Advanced example using the "element" field
lqv $v08,e(2), 0x08,a0   // read bytes 0x08(a0) - 0x0F(a0) into VPR[vt][4..11]
lrv $v08,e(2), 0x18,a0   // read bytes 0x10(a0) - 0x13(a0) into VPR[vt][12..15]


</syntaxhighlight>Notice that the element field is optional (defaults to 0) and is usually not specified because these instructions are meant to affect the whole vector. The element field can be specified using the lane syntax (<code>e(N)</code>) or a raw number which maps to the byte offset inside the vector.

===== Pseudo-code =====
<syntaxhighlight lang="c">
// lqv
addr = GPR[base] + (offset * 16)
end = addr | 15
size = MIN(end-addr, 15-element)
VPR[vt][element..element+size] = DMEM[addr..addr+size]

</syntaxhighlight><syntaxhighlight lang="c">
// lrv
end = GPR[base] + (offset * 16)
addr = end & ~16
size = MIN(end-addr, 15-element)
VPR[vt][element..addr+size] = DMEM[addr..addr+size]

</syntaxhighlight>

===== Description =====
Roughly, these functions behave like <code>lwl</code> and <code>lwr</code>: combined, they allow to read 128 bits of data into a vector register, irrespective of the alignment. 

When the data to be loaded is 128-bit aligned within DMEM, <code>lqv</code> is sufficient to read the whole vector (<code>lrv</code> in this case is redundant because it becomes a no-op).

The actual bytes accessed in DMEM depend on the instruction: for <code>lwv</code>, the bytes are those starting at <code>GPR[base] + (offset * 16)</code>, up to and excluding the next 128-bit aligned byte (<code>a0+0x10</code> in the above example); for <code>lrv</code>, the bytes are those starting at the previous 128-bit aligned byte (<code>a0+0x10</code> in the above example) up to and ''excluding'' <code>GPR[base] + (offset * 16)</code>. Again, this is exactly the same behavior of <code>lwl</code> and <code>lwr</code>, but for 128-bit aligned loads.

<code>element</code> is used as a byte offset within the vector register to specify the first byte affected by the operation; that is, the part of the vector being loaded with the instruction pair is <code>VPR[vt][element..15]</code>. Thus a non-zero element means that fewer bytes are loaded.

===== Usage =====
<code>lqv</code> is the most standard way to fill a full VPR vector register loading its contents from DMEM. Given that it's usually possible to define the layout of data in DMEM, it is advisable to design it so that vectors are always aligned to 128-bit (16 bytes), using the <code>.align 4</code> directory: this allows to read the vector using just <code>lqv</code>, in 1 cycle (though the load has a 3-cycle latency like all instructions that write to a VPR).<syntaxhighlight lang="asm">
    .data

    .align 4
CONST:  .half 3, 2, 7, 0, 0x4000, 0x8000, 0x7F, 0xFFF      # Several constants used for an algorithm

    .text
    
    lqv $v31, %lo(CONST),r0    # Load the constants    

</syntaxhighlight>One example of using <code>lqv</code> and <code>lrv</code> in pair is to perform a fast memcpy from a possible misaligned address to an aligned destination buffer:<syntaxhighlight lang="asm">
    # s0 is the pointer to source data in DMEM (possibly misaligned)
    # s4 will point to the destination buffer in DMEM (aligned)
    # t1 is the number of bytes to copy
    li s4, %lo(BUFFER)
loop:
    lqv $v00, 0x00,s0
    lrv $v00, 0x10,s0
    sqv $v00, 0,s4
    sub t1, 16
    add s0, 16
    bgtz t1, loop
    add s4, 16

</syntaxhighlight>
