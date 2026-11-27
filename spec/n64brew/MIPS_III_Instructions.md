<!--
  Source: https://n64brew.dev/wiki/MIPS_III_instructions
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The NEC VR4300 uses an instruction set that is nearly identical to that of the MIPS III Instruction Set Architecture (ISA). While the instruction set is explained in detail in the [[:File:VR4300-Users-Manual.pdf|VR4300 datasheet]], this article serves as a reformatted reference for those same instructions, including any quirks or additional reminders that are useful when programming something for the N64. See also [[MIPS Assembly]].

If you are looking for instructions to perform certain actions, use your browser's search feature with <code>CTRL+F</code>.

= Instruction Notation Key =
{{#invoke:Instruction set table builder|notation
| base | An immediate value which represents a base address
| cofun | Coprocessor function
| r | 64-bit register
| r{{sub|d}} | Destination register
| r{{sub|s}} | Source register
| r{{sub|t}} | Temporary register
| GPR | General Purpose Register
| GPR[r] | The general purpose register 'r'
| label | Label name
| immediate | A hardcoded value via an assembler variable or literal
| offset | An immediate value added to base address to form a virtual address
| sa | Shift this number of bits left or right
| [[w:Sign_extension|sign-extended]] | Extends the upper bits with 1's or 0's to preserve the sign and value of the number
| [[w:Sign_extension#Zero_extension|zero-extended]] | Extends the upper bits with 0's.
}}

= CPU Instruction Set =
Every instruction has a 32-bit instruction word that the CPU uses to identify the instruction and any arguments used in it. The upper 6 bits is the instruction's opcode, however some instructions use additional constant bits to further define the operation. For example, the SPECIAL opcode is used for numerous instructions including ADD, SUB, AND, BREAK, and more.
{{#invoke:Instruction set table builder|notation
| s | source register number
| d | destination register number
| t | temporary register number
| k | literal/immediate value
| b | base address
| f | offset address
| x | coprocessor number
}}

Typically an assembler will be used when programming in order to format the proper instruction word, when generating a ROM file. '''Most developers can safely ignore the instruction word column entirely.'''

''However, most assemblers implement '''branch instructions''' differently! Instead of an offset value, they usually require the use of a label or absolute address.''
{{#invoke:Instruction set table builder|set
| ADD     | rd, rs, rt        | Add rs and rt, store result in rd | 000000 sssss ttttt ddddd 00000 100000
| ADDI    | rt, rs, immediate | Add sign-extended 16bit immediate and rs, store result in rt | 001000 sssss ttttt kkkkkkkkkkkkkkkk
| ADDIU   | rt, rs, immediate | Add sign-extended 16bit immediate and rs, store result in rt | 001001 sssss ttttt kkkkkkkkkkkkkkkk
| ADDU    | rd, rs, rt        | Add rs and rt, store result in rd | 000000 sssss ttttt ddddd 00000 100001
| AND     | rd, rs, rt        | AND rs with rt, store result in rd | 000000 sssss ttttt ddddd 00000 100100
| ANDI    | rt, rs, immediate | AND rs with zero-extended immediate, store result in rt | 001100 sssss ttttt kkkkkkkkkkkkkkkk

| BCzF    | offset            | If CPz's CpCond is false, branch to address (delay slot + offset) | 0100xx 01000 00000 ffffffffffffffff
| BCzFL   | offset            | If CPz's CpCond is false, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 0100xx 01000 00010 ffffffffffffffff
| BCzT    | offset            | If CPz's CpCond is true, branch to address (delay slot + offset) | 0100xx 01000 00001 ffffffffffffffff
| BCzTL   | offset            | If CPz's CpCond is true, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 0100xx 01000 00011 ffffffffffffffff

| BEQ     | rs, rt, offset    | If rs equals rt, branch to address (delay slot + offset) | 000100 sssss ttttt ffffffffffffffff
| BEQL    | rs, rt, offset    | If rs equals rt, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 010100 sssss ttttt ffffffffffffffff

| BGEZ    | rs, offset        | If rs is greater than or equal to zero, branch to address (delay slot + offset) | 000001 sssss 00001 ffffffffffffffff
| BGEZAL  | rs, offset        | If rs is greater than or equal to zero, branch to address (delay slot + offset) and store next address to r31 | 000001 sssss 10001 ffffffffffffffff
| BGEZALL | rs, offset        | If rs is greater than or equal to zero, branch to address (delay slot + offset) and store next address to r31, otherwise discar'd delay slot instruction | 000001 sssss 10011 ffffffffffffffff
| BGEZL   | rs, offset        | If rs is greater than or equal to zero, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 000001 sssss 00011 ffffffffffffffff

| BGTZ    | rs, offset        | If rs is greater than zero, branch to address (delay slot + offset) | 000111 sssss 00000 ffffffffffffffff
| BGTZL   | rs, offset        | If rs is greater than zero, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 010111 sssss 00000 ffffffffffffffff

| BLEZ    | rs, offset        | If rs is less than or equal to zero, branch to address (delay slot + offset) | 000110 sssss 00000 ffffffffffffffff
| BLEZL   | rs, offset        | If rs is less than or equal to zero, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 010110 sssss 00000 ffffffffffffffff

| BLTZ    | rs, offset        | If rs is less than zero, branch to address (delay slot + offset) | 000001 sssss 00000 ffffffffffffffff
| BLTZAL  | rs, offset        | If rs is less than zero, branch to address (delay slot + offset) and store next address to r31 | 000001 sssss 10000 ffffffffffffffff
| BLTZALL | rs, offset        | If rs is less than zero, branch to address (delay slot + offset) and store next address to r31, otherwise discar'd delay slot instruction | 000001 sssss 10010 ffffffffffffffff
| BLTZL   | rs, offset        | If rs is less than zero, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 000001 sssss 00010 ffffffffffffffff

| BNE     | rs, rt, offset    | If rs is not equal to rt, branch to address (delay slot + offset) | 000101 sssss ttttt ffffffffffffffff
| BNEL    | rs, rt, offset    | If rs is not equal to rt, branch to address (delay slot + offset), otherwise discar'd delay slot instruction | 010101 sssss ttttt ffffffffffffffff
	
| BREAK   | &nbsp;            | Causes breakpoint exception | 000000 kkkkkkkkkkkkkkkkkkkk 001101
| CACHE   | op, offset(base)  | Flush instruction or data cache at address (base + offset) to RAM | 101111 bbbbb kkkkk ffffffffffffffff

| CFCz    | rt, rd            | Copy contents of CPz control register rd, to GPR rt | 0100xx 00010 ttttt ddddd 00000000000
| COPz    | cofun             | Perform coprocessor operation | 0100xx 1 kkkkkkkkkkkkkkkkkkkkkkkkk
| CTCz    | rt, rd            | Copy contents of GPR rt, to CPz control register rd | 0100xx 00110 ttttt ddddd 00000000000

| DADD    | rd, rs, rt        | Add rs and rt, store result in rd (mode restrictions) | 000000 sssss ttttt ddddd 00000 101100
| DADDI   | rt, rs, immediate | Add sign-extended 16bit immediate and rs, store result in rt (mode restrictions) | 011000 sssss ttttt kkkkkkkkkkkkkkkk
| DADDIU  | rt, rs, immediate | Add sign-extended 16bit immediate and rs, store result in rt (mode restrictions) | 011001 sssss ttttt kkkkkkkkkkkkkkkk
| DADDU   | rd, rs, rt        | Add rs and rt, store result in rd (mode restrictions) | 000000 sssss ttttt ddddd 00000 101101
| DDIV    | rs, rt            | Divide signed rs by signed rt, store quotient in register LO and remainder in HI (mode restrictions) | 000000 sssss ttttt 0000000000 011110
| DDIVU   | rs, rt            | Divide unsigned rs by unsigned rt, store quotient in register LO and remainder in HI (mode restrictions) | 000000 sssss ttttt 0000000000 011111
| DIV     | rs, rt            | Divide signed rs by signed rt, store quotient in register LO and remainder in HI | 000000 sssss ttttt 0000000000 011010
| DIVU    | rs, rt            | Divide unsigned rs by unsigned rt, store quotient in register LO and remainder in HI | 000000 sssss ttttt 0000000000 011011

| DMFC0   | rt, rd            | Copy doublewor'd contents of CPz coprocessor register rd, to GPR rt | 010000 00001 ttttt ddddd 00000000000
| DMTC0   | rt, rd            | Copy doublewor'd contents of GPR rt, to CPz coprocessor register rd | 010000 00101 ttttt ddddd 00000000000

| DMULT   | rs, rt            | Multiply signed rs with signed rt, store low-order doublewor'd in LO, and high-order doublewor'd to HI (mode restrictions) | 000000 sssss ttttt 0000000000 011100
| DMULTU  | rs, rt            | Multiply unsigned rs with unsigned rt, store low-order doublewor'd in LO, and high-order doublewor'd to HI (mode restrictions) | 000000 sssss ttttt 0000000000 011101

| DSLL    | rd, rt, sa        | Shift rt left by sa bits, store result in rd (mode restrictions) | 000000 00000 ttttt ddddd kkkkk 111000
| DSLLV   | rd, rt, rs        | Shift rt left by rs (limited to 63), store result in rd (mode restrictions) | 000000 sssss ttttt ddddd 00000 010100
| DSLL32  | rd, rt, rs        | Shift rt left by (32 + sa) bits, store result in rd (mode restrictions) | 000000 00000 ttttt ddddd kkkkk 111100
| DSRA    | rd, rt, sa        | Shift rt right by sa bits, store sign-extended result in rd (mode restrictions) | 000000 00000 ttttt ddddd kkkkk 111011
| DSRAV   | rd, rt, rs        | Shift rt right by rs (limited to 63), store sign-extended result in rd (mode restrictions) | 000000 sssss ttttt ddddd 00000 010111
| DSRA32  | rd, rt, sa        | Shift rt right by (32 + sa) bits, store sign-extended result in rd (mode restrictions) | 000000 00000 ttttt ddddd kkkkk 111111
| DSRL    | rd, rt, sa        | Shift rt right by sa bits, store sign-extended result in rd (mode restrictions) | 000000 00000 ttttt ddddd kkkkk 111010
| DSRLV   | rd, rt, rs        | Shift rt right by rs (limited to 63), store sign-extended result in rd (mode restrictions) | 000000 sssss ttttt ddddd 00000 010110
| DSRL32  | rd, rt, sa        | Shift rt right by (32 + sa) bits, store sign-extended result in rd (mode restrictions) | 000000 00000 ttttt ddddd kkkkk 111110

| DSUB    | rd, rs, rt        | Subtract rt from rs, store result in rd | 000000 sssss ttttt ddddd 00000 101110
| DSUBU   | rd, rs, rt        | Subtract rt from rs, store result in rd | 000000 sssss ttttt ddddd 00000 101111

| ERET    | &nbsp;            | Return from interrupt, exception, or error exception | 010000 1 0000000000000000000 011000
| J       | target            | Jump to target address | 000010 kkkkkkkkkkkkkkkkkkkkkkkkkk
| JAL     | target            | Jump to target address, stores return address in r31 | 000011 kkkkkkkkkkkkkkkkkkkkkkkkkk
| JALR    | rd, rs            | Jump to address stored in rs, stores return address in rd | 000000 sssss 00000 ddddd 00000 001001
| JALR    | rs                | Jump to address stored in rs, stores return address in r31 | 000000 sssss 00000 11111 00000 001001
| JR      | rs                | Jump to address stored in rs | 000000 sssss 000000000000000 001000

| LB      | rt, offset(base)  | Loads byte stored at memory address (base + offset), stores sign-extended byte in rt | 100000 bbbbb ttttt ffffffffffffffff
| LBU     | rt, offset(base)  | Loads byte stored at memory address (base + offset), stores zero-extended byte in rt | 100100 bbbbb ttttt ffffffffffffffff
| LD      | rt, offset(base)  | Loads doublewor'd stored at memory address (base + offset), stores doublewor'd in rt | 110111 bbbbb ttttt ffffffffffffffff

| LDCz    | rt, offset(base)  | Copies doublewor'd stored at memory address (base + offset), to CPz | 1101xx bbbbb ttttt ffffffffffffffff

| LDL     | rt, offset(base)  | Loads a por'tion of a doublewor'd beginning at memory address (base + offset), stores 1-8 bytes in high-order por'tion of rt | 011010 bbbbb ttttt ffffffffffffffff
| LDR     | rt, offset(base)  | Loads a por'tion of a doublewor'd beginning at memory address (base + offset), stores 1-8 bytes in low-order por'tion of rt | 011011 bbbbb ttttt ffffffffffffffff

| LH      | rt, offset(base)  | Loads halfwor'd stored at memory address (base + offset), stores sign-extended halfwor'd in rt | 100001 bbbbb ttttt ffffffffffffffff
| LHU     | rt, offset(base)  | Loads halfwor'd stored at memory address (base + offset), stores zero-extended halfwor'd in rt | 100101 bbbbb ttttt ffffffffffffffff
| LL      | rt, offset(base)  | Load Linked (Refer to section below) | 110000 bbbbb ttttt ffffffffffffffff
| LLD     | rt, offset(base)  | Load Linked Doublewor'd (Refer to section below) | 110100 bbbbb ttttt ffffffffffffffff
| LUI     | rt, immediate     | 16-bit immediate is shifted left 16 bits using trailing zeros, result placed in rt | 001111 00000 ttttt kkkkkkkkkkkkkkkk
| LW      | rt, offset(base)  | Loads wor'd stored at memory address (base + offset), stores sign-extended wor'd in rt | 100011 bbbbb ttttt ffffffffffffffff

| LWCz    | rt, offset(base)  | Copies wor'd stored at memory address (base + offset), to CPz | 1100xx bbbbb ttttt ffffffffffffffff

| LWL     | rt, offset(base)  | Loads a por'tion of a wor'd beginning at memory address (base + offset), stores 1-4 bytes in high-order por'tion of rt | 100010 bbbbb ttttt ffffffffffffffff
| LWR     | rt, offset(base)  | Loads a por'tion of a wor'd beginning at memory address (base + offset), stores 1-4 bytes in low-order por'tion of rt | 100110 bbbbb ttttt ffffffffffffffff

| LWU     | rt, offset(base)  | Loads wor'd stored at memory address (base + offset), stores zero-extended wor'd in rt | 100111 bbbbb ttttt ffffffffffffffff

| MFC0    | rt, rd            | Copy contents of CP0's coprocessor register rd, to GPR rt | 010000 00000 ttttt ddddd 00000000000
| MFCz    | rt, rd            | Copy contents of CPz's coprocessor register rd, to GPR rt | 0100xx 00000 ttttt ddddd 00000000000

| MFHI    | rd                | Copy contents of register HI to rd (warning: hazard) | 000000 0000000000 ddddd 00000 010000
| MFLO    | rd                | Copy contents of register LO to rd (warning: hazard) | 000000 0000000000 ddddd 00000 010010

| MTC0    | rt, rd            | Copy contents of GPR rt, to CP0's coprocessor register rd | 010000 00100 ttttt ddddd 00000000000
| MTCz    | rd, rd            | Copy contents of GPR rt, to CPz's coprocessor register rd | 0100xx 00100 ttttt ddddd 00000000000

| MTHI    | rs                | Copy contents of rs to register HI | 000000 sssss 000000000000000 010001
| MTLO    | rs                | Copy contents of rs to register LO | 000000 sssss 000000000000000 010011

| MULT    | rs, rt            | Multiply signed rs by signed rt, store low-order wor'd of result in register LO and high-order wor'd in HI | 000000 sssss ttttt 0000000000 011000
| MULTU   | rs, rt            | Multiply unsigned rs by unsigned rt, store low-order wor'd of result in register LO and high-order wor'd in HI | 000000 sssss ttttt 0000000000 011001

| NOR     | rd, rs, rt        | NOR rs and rt, store result in rd | 000000 sssss ttttt ddddd 00000 100111
| OR      | rd, rs, rt        | OR rs and rt, store result in rd | 000000 sssss ttttt ddddd 00000 100101
| ORI     | rt, rs, immediate | OR rs and zero-extended immediate, store result in rt | 001101 sssss ttttt kkkkkkkkkkkkkkkk

| SB      | rt, offset(base)  | Stores least-significant byte from rt, to memory address (base + offset) | 101000 bbbbb ttttt ffffffffffffffff
| SC      | rt, offset(base)  | If LL bit is set, stores contents of rt, to memory address (base + offset) | 111000 bbbbb ttttt ffffffffffffffff
| SCD     | rt, offset(base)  | If LLD bit is set, stores contents of rt, to memory address (base + offset) (mode restrictions) | 111100 bbbbb ttttt ffffffffffffffff
| SD      | rt, offset(base)  | Stores doublewor'd from rt, to memory address (base + offset) | 111111 bbbbb ttttt ffffffffffffffff

| SDCz    | rt, offset(base)  | Copies doublewor'd from CPz, to memory address (base + offset) | 1111xx bbbbb ttttt ffffffffffffffff
| SDL     | rt, offset(base)  | Loads a por'tion of rt, stores 1-8 bytes in high-order por'tion of memory address (base + offset) | 101100 bbbbb ttttt ffffffffffffffff
| SDR     | rt, offset(base)  | Loads a por'tion of rt, stores 1-8 bytes in low-order por'tion of memory address (base + offset) | 101101 bbbbb ttttt ffffffffffffffff
| SH      | rt, offset(base)  | Stores halfwor'd from rt, to memory address (base + offset) | 101001 bbbbb ttttt ffffffffffffffff

| SLL     | rd, rt, sa        | Shift rt left by sa bits, store result in rd | 000000 00000 ttttt ddddd kkkkk 000000
| SLLV    | rd, rt, rs        | Shift rt left by rs (limited to 31), store result in rd | 000000 sssss ttttt ddddd 00000 000100

| SLT     | rd, rs, rt        | If signed rs is less than signed rt, store one in rd, otherwise store zero  | 000000 sssss ttttt ddddd 00000 101010
| SLTI    | rt, rs, immediate | If signed rs is less than sign-extended immediate, store one in rd, otherwise store zero | 001010 sssss ttttt kkkkkkkkkkkkkkkk
| SLTIU   | rt, rs, immediate | If unsigned rs is less than sign-extended immediate, store one in rt, otherwise store zero | 001011 sssss ttttt kkkkkkkkkkkkkkkk
| SLTU    | rd, rs, rt        | If unsigned rs is less than unsigned rt, store one in rd, otherwise store zero | 000000 sssss ttttt ddddd 00000 101011

| SRA     | rd, rt, sa        | Shift rt right by sa bits, store sign-extended result in rd | 000000 00000 ttttt ddddd kkkkk 000011
| SRAV    | rd, rt, rs        | Shift rt right by rs (limited to 31), store sign-extended result in rd | 000000 sssss ttttt ddddd 00000 000111
| SRL     | rd, rt, sa        | Shift rt right by sa bits, store sign-extended result in rd | 000000 00000 ttttt ddddd kkkkk 000010
| SRLV    | rd, rt, rs        | Shift rt right by rs (limited to 31), store sign-extended result in rd | 000000 sssss ttttt ddddd 00000 000110

| SUB     | rd, rs, rt        | Subtract rt from rs, store result in rd | 000000 sssss ttttt ddddd 00000 100010
| SUBU    | rd, rs, rt        | Subtract rt from rs, store result in rd | 000000 sssss ttttt ddddd 00000 100011

| SW      | rt, offset(base)  | Stores wor'd from rt, to memory address (base + offset) | 101011 bbbbb ttttt ffffffffffffffff

| SWCz    | rt, offset(base)  | Copies wor'd from CPz, to memory address (base + offset) | 1110xx bbbbb ttttt ffffffffffffffff

| SWL     | rt, offset(base)  | Loads a por'tion of rt, stores 1-4 bytes in high-order por'tion of memory address (base + offset) | 101010 bbbbb ttttt ffffffffffffffff
| SWR     | rt, offset(base)  | Loads a por'tion of rt, stores 1-4 bytes in low-order por'tion of memory address (base + offset) | 101110 bbbbb ttttt ffffffffffffffff

| SYNC    | &nbsp;            | Executed as NOP on the VR4300 | 000000 00000000000000000000 001111
| SYSCALL | &nbsp;            | Causes system call exception | 000000 kkkkkkkkkkkkkkkkkkkk 001100

| TEQ     | rs, rt            | If rs equals rt, cause a trap exception | 000000 sssss ttttt kkkkkkkkkk 110100
| TEQI    | rs, immediate     | If rs equals sign-extended immediate, cause a trap exception | 000001 sssss 01100 kkkkkkkkkkkkkkkk
| TGE     | rs, rt            | If signed rs is greater than or equal to signed rt, cause a trap exception | 000000 sssss ttttt kkkkkkkkkk 110000
| TGEI    | rs, immediate     | If signed rs is greater than or equal to sign-extended immediate, cause a trap exception | 000001 sssss 01000 kkkkkkkkkkkkkkkk
| TGEIU   | rs, immediate     | If unsigned rs is greater than or equal to sign-extended immediate, cause a trap exception | 000001 sssss 01001 kkkkkkkkkkkkkkkk
| TGEU    | rs, rt            | If unsigned rs is greater than or equals to unsigned rt, cause a trap exception | 000000 sssss ttttt kkkkkkkkkk 110001

| TLBP    | &nbsp;            | Searches for a TLB entry that matches the EntryHi register | 010000 1 0000000000000000000 001000
| TLBR    | &nbsp;            | Loads EntryHi and EntryLo registers with the TLB entry pointed at by the Index register | 010000 1 0000000000000000000 000001
| TLBWI   | &nbsp;            | Stores the contents of EntryHi and EntryLo registers into the TLB entry pointed at by the Index register | 010000 1 0000000000000000000 000010
| TLBWR   | &nbsp;            | Stores the contents of EntryHi and EntryLo registers into the TLB entry pointed at by the Random register | 010000 1 0000000000000000000 000110

| TLT     | rs, rt            | If signed rs is less than signed rt, cause a trap exception | 000000 sssss ttttt kkkkkkkkkk 110010
| TLTI    | rs, immediate     | If signed rs is less than sign-extended immediate, cause a trap exception | 000001 sssss 01010 kkkkkkkkkkkkkkkk
| TLTIU   | rs, immediate     | If unsigned rs is less than sign-extended immediate, cause a trap exception | 000001 sssss 01011 kkkkkkkkkkkkkkkk
| TLTU    | rs, rt            | If unsigned rs is less than unsigned rt, cause a trap exception | 000000 sssss ttttt kkkkkkkkkk 110011
| TNE     | rs, rt            | If rs does not equal rt, cause a trap exception | 000000 sssss ttttt kkkkkkkkkk 110110
| TNEI    | rs, immediate     | If rs does not equal sign-extended immediate, cause a trap exception | 000001 sssss 01110 kkkkkkkkkkkkkkkk

| XOR     | rd, rs, rt        | XOR rs with rt, store result in rd | 000000 sssss ttttt ddddd 00000 100110
| XORI    | rt, rs, immediate | XOR rs with zero-extended immediate, store result in rd | 001110 sssss ttttt kkkkkkkkkkkkkkkk
}}

== Hazards ==
The <code>mfhi</code> and <code>mflo</code> instructions will produce incorrect results if any of the two following instructions modify the <code>HI</code> and <code>LO</code> registers, respectively. Note that by default, assemblers other than Bass will prevent this by reordering instructions or inserting <code>nop</code>. If you are using <code>.set noreorder</code> or Bass, you must ensure this yourself.

== ADD ==
'''Format:''' ADD rd, rs, rt
{{term| Description:}}
{{defn|defn= The contents of general purpose register rs and the contents of general purpose register rt are added to store the result in general purpose register rd. In 64-bit mode, the operands must be sign-extended, 32-bit values. An integer overflow exception occurs if the carries out of bits 30 and 31 differ (2’s complement overflow). The contents of destination register rd is not modified when an integer overflow exception occurs.}}
{{term| Exceptions:}}
{{defn|defn= Integer overflow exception}}

== ADDI ==
'''Format:''' ADDI rt, rs, immediate
{{term| Description:}}
{{defn|defn= The 16-bit immediate is sign-extended and added to the contents of general purpose register rs to store the result in general purpose register rt. In 64-bit mode, the operand must be sign-extended, 32-bit values. An integer overflow exception occurs if carries out of bits 30 and 31 differ (2’s complement overflow). The contents of destination register rt is not modified when an integer overflow exception occurs.}}
{{term| Exceptions:}}
{{defn|defn= Integer overflow exception}}


<br><br>''TODO''

= FPU Instruction Set =
The floating point unit (FPU) is contained within the VR3400 microprocessor and handles floating point operations. The FPU uses a different set of registers for its operations (f0 - f31). While these registers are separate from general purpose registers, they function the same way.
{{#invoke:Instruction set table builder|notation
| f{{sub|d}} | Destination register
| f{{sub|s}} | Source register
| f{{sub|t}} | Temporary register
| fmt | Operand format
| FPR | Floating-point Register
}}
Many FPU instructions require an operand format <code>fmt</code>. This format dictates the size of the operators and whether they are floating-point or fixed-point, as noted in this table:
{{#invoke:Instruction set table builder|notation
| S | 32 bits, floating-point
| D | 64 bits, floating-point
| W | 32 bits, fixed-point
| L | 64 bits, fixed-point
}}
Some instructions will also require a conditional <code>cond</code>. This determines what kind of comparison is performed.
{{#invoke:Instruction set table builder|notation
| - | '''table incomplete'''
| F | T
| UN | OR
| EQ | NEQ
| UEQ | OGL
| OLT | UGE
| ULT | OGE
| OLE | UGT
| ULE | OGT

| SF | ST
| NGLE | GLE
| SEQ | SNE
| NGL | GL
| LT | NLT
| NGE | GE
| LE | NLE
| NGT | GT
}}
'''Instruction Word Key'''
{{#invoke:Instruction set table builder|notation
| s | source register number
| d | destination register number
| t | temporary register number
| k | literal/immediate value
| b | base address
| f | offset address
| x | coprocessor number
| a | fmt - operand format
| c | cond - conditional 
}}
{{#invoke:Instruction set table builder|set
| ABS.fmt     | fd, fs        | Absolute value of fs, store result in fd | 010001 aaaaa 00000 sssss ddddd 000101
| ADD.fmt     | fd, fs        | Add fs and ft, store result in fd | 010001 aaaaa ttttt sssss ddddd 000000
| C.cond.fmt  | fs, ft        | Compares fs and ft using cond  | 010001 aaaaa ttttt sssss 00000 11cccc

| BC1F        | offset        | &nbsp; | 010001 01000 00000 ffffffffffffffff
| BC1FL       | offset        | &nbsp; | 010001 01000 00010 ffffffffffffffff
| BC1T        | offset        | &nbsp; | 010001 01000 00001 ffffffffffffffff
| BC1TL       | offset        | &nbsp; | 010001 01000 00011 ffffffffffffffff
}}

''TODO''

= Pseudo-Instructions =
Many assemblers, regardless of architecture, will add additional instructions to assist developers. This table shows the instructions added by the [https://github.com/ARM9/bass bass assembler], which is commonly used to develop N64 ROMs.
