<!--
  Source: https://n64brew.dev/wiki/COP1
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

== Overview ==
The COP1 is the FPU of the main CPU. It operates on floats (either 32 bit singles or 64 bit doubles).

Just like the main CPU, the COP1 has 32 registers which are each 64 bit wide. Unlike the main CPU registers, all registers are equal (there is no zero register).

== Getting data to/from the COP1 ==
Numbers can be passed from main registers to FPU registers via MTC1 (32 bit) and DMTC1 (64 bit). For the way back, use MFC1/DMFC1. Alternatively, numbers can be loaded from RAM via LWC1/LDC1 and stored via SWC1/SDC1.

== Supported formats and conversions ==
The instructions above simply transfer bits. In order to actually calculate, they need to be interpreted correctly. The COP1 understands four formats:
{| class="wikitable"
|+ Supported formats
|-
! Name !! Abbreviation !! Explanation
|-
| Single || S || 32 bit float
|-
| Double || D || 64 bit float
|-
| Word || W || 32 bit integer
|-
| Long || Long || 64 bit integer
|}

The COP1 can only perform calculations on singles and doubles; word and long are temporary formats merely used for conversion.

Example: The following snippet puts 6 into V0, which is then moved to the COP1 into F0. It then converts that number to a double and puts it into F2. At the end, F2 will have the value 6.0:
<code><pre>
ORI V0, R0, 6
MTC1 V0, F0
CVT.D.W F2, F0   // read: convert to Double from Word
</pre></code>

The COP1 supports almost all conversions:

{| class="wikitable"
|+ Supported conversions
|-
!  !! From Single !! From Double !! From Word !! From Long
|-
| To Single || N/A || CVT.S.D || CVT.S.W || CVT.S.L
|-
| To Double || CVT.D.S || N/A || CVT.D.W || CVT.D.L
|-
| To Word || CVT.W.S || CVT.W.D || N/A || (doesn't exist)
|-
| To Long || CVT.L.S || CVT.L.D || (doesn't exist) || N/A
|}

== Rounding modes and inexact results ==
Most of conversions mentioned above, but also most regular instructions can be lossy. When that happens, the COP1 has to perform some sort of rounding to fit the result in the destination. It provides four modes:
* ROUND: Round towards nearest number (e.g. 4.4 => 4 and 4.6 => 5), ties are broken by rounding to the nearest even number (e.g. 4.5 => 4 while 5.5 => 6).
* TRUNC: Round towards zero (e.g. 4.9 => 4 and -4.9 => 4).
* CEIL: Round towards larger number (e.g. 4.1 => 5 and -4.1 => -4).
* FLOOR: Round towards smaller number (e.g. 4.9 => 4 and -4.9 => -5).

The COP1 has a configurable rounding mode in FCSR (see below), which is applied for most instructions where it's applicable. For the specific case of float->int conversions, it provides specialized instructions that overwrite the global rounding mode: ROUND.x.y, TRUNC.x.y, CEIL.x.y, FLOOR.x.y (where x is either W or L and y is either S or D; all 16 combinations are supported).

When rounding happens, inexact is signaled (see exceptions below).

== FCSR ==
In addition to the data registers, the COP1 also provides the Floating Point Status Register, is read via CFC1 and written through CTC1 (using index 31). It provides the following bits:

{| class="wikitable"
|+ FCSR
|-
! Bits !! Description
|-
| 0 to 1 || RoundingMode: Nearest (ROUND) = 0, Zero (TRUNC) = 1, PositiveInfinity (CEIL) = 2, NegativeInfinity (FLOOR) = 3
|-
| 2 || Flag: Inexact Operation
|-
| 3 || Flag: Underflow
|-
| 4 || Flag: Overflow
|-
| 5 || Flag: Division By Zero
|-
| 6 || Flag: Invalid Operation
|-
| 7 || Enable: Inexact Operation
|-
| 8 || Enable: Underflow
|-
| 9 || Enable: Overflow
|-
| 10 || Enable: Division By Zero
|-
| 11 || Enable: Invalid Operation
|-
| 12 || Cause: Inexact Operation
|-
| 13 || Cause: Underflow
|-
| 14 || Cause: Overflow
|-
| 15 || Cause: Division By Zero
|-
| 16 || Cause: Invalid Operation
|-
| 17 || Cause: Unimplemented Operation
|-
| 23 || Condition
|-
| 24 || Flush Denorm To Zero
|}

== Exceptions Overview ==
The COP1 supports 6 exceptions:
* Inexact: The destination can't hold the full result, so some data loss occurred and rounding was performed.
* Underflow: The resulting number was so small it was rounded to 0. This is always in combination with inexact. (The COP1 has a quirk here: Unlike other CPUs (e.g. x64 or arm64), the rounding modes FLOOR/CEIL are taken literally even on underflow; if the result is smaller than the smallest possible float, it might not be rounded to 0 but to the minimum regular float).
* Overflow: The resulting number was so large it couldn't be represented as a regular number and was instead "rounded up to infinity" (which is a special floating point value). This is always in combination with inexact. 
* Division By Zero: This just happens for DIV.S and DIV.D when the divisor is 0.
* Invalid Operation: This happens in a bunch of special cases (see "Special Cases" below).
* Unimplemented Operation: This happens in a bunch of special cases (see "Special Cases" below).

Instructions that can fire exceptions (e.g. ADD.S, CVT.S.W) always clear all Cause bits that aren't being signaled in this specific instructions. For example, CVT.W.S from 5.5 to an int would affect the bits in the following way:
* Clear all Cause bits
* Perform operation
* Set "Cause: Inexact"
* If "Enable: Inexact" is true, fire exception. Otherwise, set "Flag: Inexact" and put result value into destination register.

This means that Cause be looked at to see the result of the directly preceding instruction. Flags however are cumulative: They are true if any instruction since the last clear signaled that exception, assuming the exception was disabled.

Unimplemented Operation is special as it can't be disabled - if it happens, it will always fire.

== Floating Point Numbers ==
At this point, it makes sense to take a quick look at what floats actually are. The following is the bit representation of a single (doubles work exactly the same, but have more bits in the exponent and the mantissa):

{| class="wikitable"
|+ Single
|-
! 31 !! 30 - 23 !! 22 - 0
|-
| Sign (1 bit) || Exponent (8 bits) || Mantissa (23 bits)
|}

If the sign bit is 0, the number is positive. If it is 1, the number is negative (because of this, a floating point number is easily negated - just XOR with 0x80000000).

There are some special cases for the exponent and mantissa:
{| class="wikitable"
|+ Special Numbers
|-
! Sign bit !! Exponent !! Mantissa !! Description
|-
| 0 || 0 || 0 || Regular zero
|-
| 1 || 0 || 0 || "Negative zero", which is considered equal to regular zero
|-
| any || 0 || != 0 || Denormal/subnormal
|-
| 0 || 0xFF || 0 || Positive Infinity
|-
| 1 || 0xFF || 0 || Negative Infinity
|-
| any || 0xFF || != 0 with highest bit 0 || qNAN (quiet Not-A-Number)<ref name="vr4300-manual-pg-218">''[[File:VR4300-Users-Manual.pdf|NEC VR4300 User's Manual]]'', p. 218</ref>
|-
| any || 0xFF || != 0 with highest bit 1 || sNAN (signaling Not-A-Number)<ref name="vr4300-manual-pg-218" />
|-
| 0 || 0<x<0xFF || any || A regular positive number
|-
| 1 || 0<x<0xFF || any || A regular negative number
|}

Note that '''the bit representation of qNAN and sNAN are reversed''' compared to the binary interchange formats defined in the IEEE-754-2008 standard and later.

Knowing this, determining special cases and certain operations can be done through simple bit operations:
<code><pre>
fn is_zero(f: u32) -> bool { f & 0x7FFF_FFFF == 0 }
fn is_subnormal(f: u32) -> bool { ((f & 0x7F80_0000) == 0) && ((f & 0x7F_FFFF) != 0) }
fn is_nan(f: u32) -> bool { ((f & 0x7F80_0000) == 0x7F80_0000) && ((f & 0x7F_FFFF) != 0) }
fn is_quiet_nan(f: u32) -> bool { (f & 0x7FC0_0000) == 0x7F80_0000) }
fn is_signaling_nan(f: u32) -> bool { (f & 0x7FC0_0000) == 0x7FC0_0000) }
fn absolute_value(f: u32) -> bool { f & 0x7FFF_FFFF }
fn negate(f: u32) -> bool { f ^ 0x8000_0000 }
</pre></code>

== Special Cases ==
The COP1 will never on its own produce either a subnormal or an sNAN. 

The following rules applies to calculating instructions (ADD.X, SUB.X, DIV.X, MUL.X, SQRT.X, ABS, NEG.X, CVT.Y.X, ROUND.Y.X, TRUNC.Y.X, FLOOR.Y.X, CEIL.Y.X, where X is S/D):
* If an input is qNAN, fire Unimplemented Operation
* If an input is subnormal, fire Unimplemented Operation
* If an input is sNAN, signal Invalid Operation and set result to qNAN (specifically 0x7FBFFFFF (for floats) or 0x7FF7FFFFFFFFFFFF (for doubles)) (exceptions: CVT.W.x and CVT.L.x also fire Unimplemented Operation as NAN can not be represented as an integer)
* Perform the operation
* If the operation underflowed, the following happens:
** If "Flush Denorm To Zero" is 1 AND "Enable: Underflow" is 0 AND "Enable: Inexact" is 0, the result is flushed and Underflow and Inexact are signaled. In most cases this means that it is set to 0 or "negative 0". (Two exception: If the rounding mode is "Ceil" and the result is positive, it will be set to the smallest positive value instead; similarly, "Floor" will set a negative result to the negative value that is closest to 0).
** Otherwise, fire Unimplemented Operations
* If the operation is invalid (for example: Infinity-Infinity, 0.0 / 0.0 or SQRT(-2)), set result to qNAN (specifically 0x7FBFFFFF (for floats) or 0x7FF7FFFFFFFFFFFF (for doubles)) and signal Invalid Operation is signaled. 
* If the operation was a division by zero, signal division by zero
* If the operation overflowed, signal Overflow and Inexact and set result to Infinite or -Infinity
* If the operation was inexact, signal inexact

MOV.S and MOV.D are special: They just copy the bits and never fire or signal exceptions. They also don't clear the Cause bits.

== Comparisons ==
The COP1 in total has 16 single compare instructions with some pretty confusing names (and another 16 for doubles). The 16 instructions are all possible combinations of the following 4 bits:
* Unordered (Bit 0): Comparison is considered true if one or both of the operands is NAN
* Equal (Bit 1): Comparison is considered true if both operands are equal (note that 0 is equal to -0, but NAN is always different from another NAN)
* Smaller (Bit 2): Comparison is considered true if the first operand is smaller than the second
* SignalOnQNAN (Bit 3): If either operand is qNAN, this will signal Invalid Operation.

If multiple bits are set, the conditions are ORed together: For example, UEQ is considered true if the two operands are equal or unordered.

Note that inputs of sNAN always signal Invalid Operation. Using all bit combinations, this gives the following instructions:

{| class="wikitable"
|+ Compare encoding
|-
! SignalOnQNAN (Bit 3) !! Smaller (Bit 2) || Equal (Bit 1) || Unordered (Bit 0) || Name || Result formula || Invalid Operation Condition
|-
| 0 || 0 || 0 || 0 || F || Result = false || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 0 || 0 || 0 || 1 || UN || Result = unordered(arg1, arg2) || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 0 || 0 || 1 || 0 || EQ || Result = arg1 == arg2 || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 0 || 0 || 1 || 1 || UEQ || Result = unordered(arg1, arg2) OR (arg1 == arg2) || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 0 || 1 || 0 || 0 || OLT || Result = arg1 < arg2 || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 0 || 1 || 0 || 1 || ULT || Result = unordered(arg1, arg2) OR (arg1 < arg2) || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 0 || 1 || 1 || 0 || OLE || Result = arg1 <= arg2 || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 0 || 1 || 1 || 1 || ULE || Result = unordered(arg1, arg2) OR (arg1 <= arg2) || IsSNAN(arg1) OR IsSNAN(arg2)
|-
| 1 || 0 || 0 || 0 || SF || Result = false || IsNAN(arg1) OR IsNAN(arg2)
|-
| 1 || 0 || 0 || 1 || NGLE || Result = unordered(arg1, arg2) || IsNAN(arg1) OR IsNAN(arg2)
|-
| 1 || 0 || 1 || 0 || SEQ || Result = arg1 == arg2 || IsNAN(arg1) OR IsNAN(arg2)
|-
| 1 || 0 || 1 || 1 || NGL || Result = unordered(arg1, arg2) OR (arg1 == arg2) || IsNAN(arg1) OR IsNAN(arg2)
|-
| 1 || 1 || 0 || 0 || LT || Result = arg1 < arg2 || IsNAN(arg1) OR IsNAN(arg2)
|-
| 1 || 1 || 0 || 1 || NGE || Result = unordered(arg1, arg2) OR (arg1 < arg2) || IsNAN(arg1) OR IsNAN(arg2)
|-
| 1 || 1 || 1 || 0 || LE || Result = arg1 <= arg2 || IsNAN(arg1) OR IsNAN(arg2)
|-
| 1 || 1 || 1 || 1 || NGT || Result = unordered(arg1, arg2) OR (arg1 <= arg2) || IsNAN(arg1) OR IsNAN(arg2)
|}

== Full Mode vs Half Mode ==
The COP1 can run in one of two modes, which is controlled via COP0.Status Bit 26. In "Full Mode", the COP1 has 32 registers that are each 64 bits wide. In "Half Mode", only the 16 even numbered registers are legal to be used; using odd numbered registers is considered undefined behavior.

Older software usually ran in "Half Mode". A reason for that could be that context switches (for multithreading) can be performed more cheaply, as only 16 FPU registers need to be stored.

When using "Half Mode" it is important to not use any FPU registers with odd indices. For compiled code this has to be configured accordingly ("+nooddspreg" in clang).

''The remainder of this section documents undefined behavior. Skip this unless you are an emulator developer who cares about accuracy a little bit too much.''

If software decides to use odd indices in "Half Mode", different things happen, depending on the instruction:

{| class="wikitable"
|+ Illegal register indexing in "Half Mode" (normally undocumented behavior - do not use)
|-
! Actual Register Index || MFC1/MTC1/LWC1/LDC1 || fd (32 bit), ft (32 bit) or any 64 bit || fs (32 bit)
|-
| 0 || 1 (high 32 bits) / 0 (low 32 bits) || 0 (low 32 bits) || 0 or 1
|-
| 1 || unused || 1 (low 32 bits) || unused
|-
| 2 || 3 (high 32 bits) / 2 (low 32 bits) || 2 (low 32 bits) || 2 or 3
|-
| 3 || unused || 3 (low 32 bits) || unused
|-
| 4 || 5 (high 32 bits) / 4 (low 32 bits) || 4 (low 32 bits) || 4 or 5
|-
| 5 || unused || 5 (low 32 bits) || unused
|}

==References==
{{reflist}}
