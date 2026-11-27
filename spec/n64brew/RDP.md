<!--
  Source: https://n64brew.dev/wiki/Reality_Display_Processor
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The '''Reality Display Processor''', or '''RDP''', is the portion of the [[RCP]] responsible for graphics tasks such as Z-buffering, texturing, blending, anti-aliasing, etc. It contains 4KB of texture memory (TMEM,) and is sent commands called "primitives".
==RDP interface==
{{Main|Reality Display Processor/Interface}}
The RDP interface is made of several memory-mapped registers that allows the VR4300 and RSP to control the RDP. Both VR4300 and RSP are in fact able to control RDP execution by accessing the interface: VR4300 through memory mapped registers, while RSP through its COP0.

== RDP commands ==
{{Main|Reality Display Processor/Commands}}
The RDP processes a fixed-function command list comprised of primitive rendering, attribute setting, texture loading, and synchronization commands. Most commands are 64-bit words, though some are bigger. Command lists can be sent to RDP via DMA, either from RDRAM or DMEM.

== RDP pipeline ==
{{Main|Reality Display Processor/Pipeline}}
The RDP is a pipelined processor with configurable pipeline modes. It is up to the user to select the appropriate operating mode and provide adequate synchronization in submitted command lists.

== RDP hazards ==
{{Main|Reality Display Processor/Hazards}}

In general, RDP programming is subject to many hazards due to the complex pipeline with user-provided synchronizations and invalid or incoherent render modes that can be setup. The effects can vary from rendering glitches to full RDP crashes that require a hard reset.



[[Category:Motherboard components]]
