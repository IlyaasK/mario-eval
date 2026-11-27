<!--
  Source: https://n64brew.dev/wiki/Audio_Interface
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The Audio Interface (or '''AI''') is one of multiple I/O interfaces in the RCP, which is used to playback audio samples. It is a very simple audio processor: it fetches samples via DMA from RDRAM at a specified rate, and then outputs them. It performs absolutely no conversion on the samples: any audio processing functionality (decompression, mixing, etc.) must be performed by either the CPU or the RSP.

Memory mapped registers are used to configure the AI and initiate DMA transfers. The base address for these registers is <code>0x0450 0000</code>, also known as AI_BASE. However, because all memory accesses in the CPU are made using virtual addresses, the following addresses must be offset appropriately. For non-cached reads/writes, add <code>0xA000 0000</code> to the address. As an example, to directly write to the AI_LENGTH register, use address <code>0xA450 0004</code>.

== DMA ==
AI allows to playback samples via a DMA channel. The CPU prepares a buffer of samples in RDRAM, then writes the AI registers to setup a DMA transfer specifying the buffer address and the length. The AI starts playing back those samples in background. Like the RSP and the RDP DMAs, also the AI DMAs has a double-buffering mechanism, so it is possible to enqueue a second buffer while the first one is playing back. This allows for continuous playback: as soon as a buffer is finished, a second is hopefully ready for playback so that the audio is uninterrupted.

The AI does not have an internal RAM holding samples: the DMA is directly connected to the DAC. This means that the DMA will progress as samples are physically put through the DAC, and the configured playback rate.

Connected to the DMA channel, there is a [[MIPS Interface#0x0430 0008 - MI INTERRUPT|IRQ triggered via MI]]. Contrary to the usual working of DMAs, the AI IRQ is triggered when a DMA transfer '''starts''', not when it ends. This can be intuitively explained: the AI wants to notify the CPU to prepare and enqueue a new buffer '''while''' a buffer is currently playing, so that the hopefully the new one will be ready by the time the current one finishes, to allow uninterrupted playback. If the AI generated the interrupt at the end of the buffer, that would be too late to enqueue a new one without audio crackings, which in turns means that the CPU wouldn't be able to rely on the IRQ for audio pacing.

AI only supports 16-bit stereo samples.

=== Delayed-carry hardware bug ===
The AI DMA has a hardware bug that triggers whenever the last sample of a DMA transfer ends exactly at the boundary of a 8KiB (0x2000) page. When this happens, AI will add 0x2000 to the address of the '''next''' buffer that will be played back, effectively playing back samples from a different address than that programmed by the CPU. 

The most likely explanation for this hardware bug is a delayed carry: maybe the AI has some internal address register split in two halves, with the lower half being 13 bits. When the lower-half register overflows (producing a carry), the carry is meant to be added to the higher-half register, but it might be that this happens 1 cycle later: if the DMA transfer ends exactly at that moment, the carry is added to the higher half at the beginning of the '''next''' transfer itself.

Libdragon has a [https://github.com/DragonMinded/libdragon/blob/14bb8848947e0e0e03fad9e12db7765c139e2c02/src/audio.c#L271-L282 workaround for this bug].


= Registers =
'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at power on
[x:y] = Specifies bits x to y, inclusively</pre>
==== <span style="display:none;">0x0450 0000 - AI_DRAM_ADDR ====
----
{{#invoke:Register table|head|550px|AI_DRAM_ADDR <code>0x0450 0000</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| colspan="8" | DRAM_ADDR[23:16]
{{#invoke:Register table|row|15:8}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| colspan="8" | DRAM_ADDR[15:8]
{{#invoke:Register table|row|7:0}}
| W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0 || W-0
|-
| colspan="5" | DRAM_ADDR[7:3] || 0 || 0 || 0
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 23-0 | DRAM_ADDR[23:0] | RDRAM address used for next DMA transfer
}}
'''Extra Details:'''
: '''Read access'''
:: The register is write-only. Reading it returns a mirror of AI_LENGTH.

==== <span style="display:none;">0x0450 0004 - AI_LENGTH ====
----
{{#invoke:Register table|head|550px|AI_LENGTH <code>0x0450 0004</code>}}
{{#invoke:Register table|row|31:24}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-? || U-? || U-? || RW-? || RW-?
|-
| — || — || — || — || — || — || colspan="2"|LENGTH[17:16]
{{#invoke:Register table|row|15:8}}
| RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-? || RW-?
|-
| colspan="8" | LENGTH[15:8]
{{#invoke:Register table|row|7:0}}
| RW-? || RW-? || RW-? || RW-? || RW-? || R-? || R-? || R-?
|-
| colspan="5" | LENGTH[7:3] || 0 || 0 || 0
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 17-0 | LENGTH[17:0] | Number of bytes of audio to send via DMA
}}
Reads return the number of bytes remaining

==== <span style="display:none;">0x0450 0008 - AI_CONTROL ====
----
{{#invoke:Register table|head|550px|AI_CONTROL <code>0x0450 0008</code>}}
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
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || W-?
|-
| — || — || — || — || — || — || — || DMA_ENABLE
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 0 | DMA_ENABLE | Enables AI DMA
}}
'''Extra Details:'''
: '''Read access'''
:: The register is write-only. Reading it returns a mirror of AI_LENGTH.

==== <span style="display:none;">0x0450 000C - AI_STATUS ====
----
{{#invoke:Register table|head|550px|AI_STATUS <code>0x0450 000C</code>}}
{{#invoke:Register table|row|31:24}}
| R-? || R-? || U-? || U-? || U-? || U-? || R-? || U-1
|-
| FULL || BUSY || 0 || 0 || — || — || ENABLED || 1
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-1 || U-? || U-? || U-? || U-?
|-
| — || — || — || 1 || WC || 0 || 0 || BC
{{#invoke:Register table|row|15:8}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| 0 || colspan="7" | COUNT[13:7] 
{{#invoke:Register table|row|7:0}}
| R-? || R-? || R-? || R-? || R-? || R-? || R-? || R-?
|-
| colspan="7" | COUNT[6:0] || FULL
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31 | FULL | Set to 1 when there is a DMA transfer pending in the DMA register in addition to a DMA already in progress.
| 30 | BUSY | Set to 1 when there is a DMA transfer currently in progress. 
| 25 | ENABLED | Reflects the bit written to AI_CONTROL
| 19 | WC | Word clock readback. This is toggled at DACRATE/2 like COUNT, though it is out-of-phase of exactly half of the period.
| 16 | BC | Bit clock readback. This is (probably) toggled for each bit shifted in, at BITRATE.
| 14-1 | COUNT | internal counter for DAC output
| 0 | FULL | Same as other copy
}}
This register is read-only. Writes to it acknowledge the AI interrupt.

'''Extra Details:'''
: '''COUNT'''
:: Count shows the internal counter used by AI to emit the various samples to the DAC. It ticks downwards at the VI clock frequency, starts at <code>DACRATE/2</code>, and ticks towards 0, and then reloads. It always ticks unless <code>AI_BITRATE</code> is 0. It is not affected by <code>DMA_ENABLE</code> in <code>AI_CONTROL</code>.
: '''BC'''
:: It is believed that this is the status of the physical BCLK line to the N64's BU9480 audio DAC. (It is only "believed" because the CPU cannot reliably sample it rapidly enough even when <code>BITRATE</code> is set to 15.) If it is BCLK, the DAC receives the next bit of audio when this changes from 0 to 1.
: '''WC'''
:: The status of the BU9480's LRCK line. (1 = left channel, 0 = right channel, rising edge = emit interpolated sample, falling edge = emit next sample)

==== <span style="display:none;">0x0450 0010 - AI_DACRATE ====
----
{{#invoke:Register table|head|550px|AI_DACRATE <code>0x0450 0010</code>}}
{{#invoke:Register table|row|31:24}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-? || U-? || U-? || U-? || U-? || U-? || U-? || U-?
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-? || U-? || W-? || W-? || W-? || W-? || W-? || W-?
|-
| — || — || colspan="6" | DACRATE[13:8]
{{#invoke:Register table|row|7:0}}
| W-? || W-? || W-? || W-? || W-? || W-? || W-? || W-?
|-
| colspan="8" | DACRATE[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 13-0 | DACRATE[13:0] | Sample period
}}
The register is write-only. Reading it returns a mirror of AI_LENGTH.

The sample rate is the Video clock, divided by one more than this number.

For example, a value of 1103 would result in a sample rate of 44136 Hz on an NTSC console.

==== <span style="display:none;">0x0450 0014 - AI_BITRATE ====
----
{{#invoke:Register table|head|550px|AI_BITRATE <code>0x0450 0014</code>}}
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
| U-? || U-? || U-? || U-? || W-? || W-? || W-? || W-?
|-
| — || — || — || — || colspan="4" | BITRATE[3:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 3-0 | BITRATE[3:0] | Half of bit clock period of I²S output to DAC
}}
The register is write-only. Reading it returns a mirror of AI_LENGTH.

The bit clock is the clock that sends single bits of each sample into the DAC. The external DAC requires some "framing" so it actually expects two clocks: one to shift each bit, and the second one (AI_DACRATE) to "close" a sample.

The bit clock rate is the Video clock, divided by two, divided by one more than this number. A written value of 0 instead stops the clock (see also `COUNT` in the AI_STATUS register).

This half-bit clock rate must at least 66 times faster than the DAC rate.

[[File:Example of clocks going into the DAC.png|thumb]]




[[Category:Motherboard components]]
