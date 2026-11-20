// n64run: headless ares frontend for mario-eval.
//
// Runs a ROM unthrottled under ares' Nintendo 64 core (CPU interpreter, so the
// data/instruction cache model applies to every instruction), feeds controller
// input keyed by *logical* game frame, and records what the ROM reports at the
// end of each logical frame over the IS-Viewer debug port:
//
//   @mev <frame> <obs_vaddr> <obs_len> <fb_paddr> <fb_w> <fb_h> <fb_bpp> <au_paddr> <au_len>\n
//
// On every such line the runner snapshots emulator-side counters (CPU clocks,
// cache events, RSP busy cycles, RDRAM bytes per bus device) and copies the
// observation record (read through the CPU data cache, i.e. what the CPU sees),
// the framebuffer and the audio buffer (read from RDRAM, i.e. what VI/AI DMA
// would see). Nothing the ROM *claims* about its own cost is used.
//
// Outputs in --out:
//   frames.jsonl   one record per logical frame (counters are cumulative)
//   video.bin      framebuffers, concatenated in frame order
//   audio.bin      audio buffers, concatenated in frame order
//   obs.bin        observation records, concatenated in frame order
//   result.json    run status, totals, RDRAM footprint
#include <ares/ares.hpp>
#include <n64/n64.hpp>
#include <mia/mia.hpp>
#include <nall/main.hpp>

#include <chrono>
#include <cstdio>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace N64 = ares::Nintendo64;

namespace {

struct Pad {
  bool a = 0, b = 0, z = 0, start = 0, l = 0, r = 0;
  bool up = 0, down = 0, left = 0, right = 0;
  bool cu = 0, cd = 0, cl = 0, cr = 0;
  int x = 0, y = 0;  // -32768..32767 (ares axis units)
};

struct Options {
  std::string rom, replay, out, profile;
  u64 frames = 0;
  u64 maxFields = 0;
  u64 boot = 0;
};

auto parsePad(const std::string& line) -> Pad {
  // "<buttons> <x> <y>" with buttons a string of letters, '.' for none,
  // stick values in N64 units (-80..80).
  Pad p;
  std::istringstream in(line);
  std::string buttons;
  int x = 0, y = 0;
  in >> buttons >> x >> y;
  for(char c : buttons) {
    switch(c) {
    case 'A': p.a = 1; break;
    case 'B': p.b = 1; break;
    case 'Z': p.z = 1; break;
    case 'S': p.start = 1; break;
    case 'L': p.l = 1; break;
    case 'R': p.r = 1; break;
    case 'u': p.up = 1; break;
    case 'd': p.down = 1; break;
    case 'l': p.left = 1; break;
    case 'r': p.right = 1; break;
    case '8': p.cu = 1; break;
    case '2': p.cd = 1; break;
    case '4': p.cl = 1; break;
    case '6': p.cr = 1; break;
    default: break;
    }
  }
  // ares maps +/-32767 to the full N64 stick range (+/-85); invert so that
  // positive y in the replay means "up", as on the controller.
  p.x = x * 32767 / 85;
  p.y = -y * 32767 / 85;
  return p;
}

struct Runner : ares::Platform {
  Options opt;
  std::shared_ptr<mia::Pak> systemPak, gamePak;
  ares::Node::System root;
  std::vector<Pad> replay;

  std::string line;
  u64 frame = 0;         // logical frames completed
  bool failed = false;
  std::string failure;

  std::ofstream jsonl, video, audio, obs;

  auto pak(ares::Node::Object node) -> std::shared_ptr<vfs::directory> override {
    if(node->name() == "Nintendo 64") return systemPak->pak;
    if(node->name() == "Nintendo 64 Cartridge") return gamePak->pak;
    return {};
  }

  auto currentPad() const -> const Pad& {
    static const Pad idle;
    // Input for the frame being computed: frame index == frames completed.
    if(frame < replay.size()) return replay[frame];
    return idle;
  }

  auto input(ares::Node::Input::Input node) -> void override {
    auto& p = currentPad();
    auto name = std::string(node->name());
    if(auto button = node->cast<ares::Node::Input::Button>()) {
      bool v = false;
      if(name == "A") v = p.a;
      else if(name == "B") v = p.b;
      else if(name == "Z") v = p.z;
      else if(name == "Start") v = p.start;
      else if(name == "L") v = p.l;
      else if(name == "R") v = p.r;
      else if(name == "Up") v = p.up;
      else if(name == "Down") v = p.down;
      else if(name == "Left") v = p.left;
      else if(name == "Right") v = p.right;
      else if(name == "C-Up") v = p.cu;
      else if(name == "C-Down") v = p.cd;
      else if(name == "C-Left") v = p.cl;
      else if(name == "C-Right") v = p.cr;
      button->setValue(v);
    } else if(auto axis = node->cast<ares::Node::Input::Axis>()) {
      if(name == "X-Axis") axis->setValue(p.x);
      else if(name == "Y-Axis") axis->setValue(p.y);
      else axis->setValue(0);
    }
  }

  auto log(ares::Node::Debugger::Tracer::Tracer node, string_view message) -> void override {
    if(std::string(node->name()) != "ISViewer") return;
    for(char c : std::string(message)) {
      if(c == '\n') { handleLine(line); line.clear(); }
      else if(line.size() < 4096) line.push_back(c);
    }
  }

  // Read bytes as the CPU would see them (through the data cache).
  auto readCpu(u32 vaddr, u32 len) -> std::vector<u8> {
    std::vector<u8> out(len);
    for(u32 i = 0; i < len; i++) {
      u64 v = vaddr + i;
      u32 paddr = v & 0x1fff'ffff;
      bool cached = (v & 0xe000'0000) == 0x8000'0000;
      if(cached) out[i] = N64::cpu.dcache.readDebug<N64::Byte>((s64)(s32)v, paddr);
      else out[i] = rawRdram(paddr);
    }
    return out;
  }

  // Read bytes as RCP DMA (VI/AI) would see them: straight from RDRAM.
  auto readRdram(u32 paddr, u32 len) -> std::vector<u8> {
    std::vector<u8> out(len);
    paddr &= 0x1fff'ffff;
    for(u32 i = 0; i < len; i++) {
      u32 a = paddr + i;
      out[i] = rawRdram(a);
    }
    return out;
  }

  // The RDRAM array without bus side effects (no profiling, no footprint).
  static auto rawRdram(u32 paddr) -> u8 {
    auto& mem = static_cast<N64::Memory::Writable&>(N64::rdram.ram);
    return paddr < mem.size ? (u8)mem.read<N64::Byte>(paddr) : 0;
  }

  auto fail(const std::string& why) -> void {
    if(!failed) { failed = true; failure = why; }
  }

  auto handleLine(const std::string& text) -> void {
    if(text.rfind("@mev ", 0) != 0) {
      if(!text.empty()) fprintf(stderr, "[rom] %s\n", text.c_str());
      return;
    }
    std::istringstream in(text.substr(5));
    u64 n; u32 obsV, obsLen, fbP, fbW, fbH, fbBpp, auP, auLen;
    in >> std::dec >> n >> std::hex >> obsV >> std::dec >> obsLen >> std::hex >> fbP
       >> std::dec >> fbW >> fbH >> fbBpp >> std::hex >> auP >> std::dec >> auLen;
    if(!in) return fail("malformed @mev line: " + text);
    if(n != frame) return fail("frame counter " + std::to_string(n) + " != expected " + std::to_string(frame));
    if(obsLen > 4096) return fail("observation record too large");
    if(fbBpp != 16 && fbBpp != 32) return fail("unsupported framebuffer depth");
    if(fbW == 0 || fbH == 0 || fbW > 640 || fbH > 480) return fail("bad framebuffer size");
    if(auLen > 64 * 1024) return fail("audio buffer too large");

    auto o = readCpu(obsV, obsLen);
    auto fb = readRdram(fbP, fbW * fbH * fbBpp / 8);
    auto au = readRdram(auP, auLen);
    obs.write((const char*)o.data(), o.size());
    video.write((const char*)fb.data(), fb.size());
    audio.write((const char*)au.data(), au.size());

    auto& cp = N64::cpu.profile;
    auto& rp = N64::rsp.profile;
    auto& dp = N64::rdp.profile;
    auto& mp = N64::rdram.profile;
    std::ostringstream j;
    j << "{\"frame\":" << n
      << ",\"count_ticks\":" << cp.cpuCycles
      << ",\"count_ticks_exc\":" << cp.cpuCyclesExc
      << ",\"icache_hits\":" << cp.icacheHits << ",\"icache_misses\":" << cp.icacheMisses
      << ",\"dcache_hits\":" << cp.dcacheHits << ",\"dcache_misses\":" << cp.dcacheMisses
      << ",\"dcache_writebacks\":" << cp.dcacheWritebacks
      << ",\"rsp_cycles\":" << rp.cycles << ",\"rsp_halted_cycles\":" << rp.haltedCycles
      << ",\"cpu_idle_cycles\":" << N64::cpu.sampler.idleClocks / 2
      << ",\"rdp_cycles\":" << dp.cycles
      << ",\"rdp_fill_cycles\":" << dp.fillCycles
      << ",\"rdp_tmem_cycles\":" << dp.tmemCycles
      << ",\"rdp_sync_cycles\":" << dp.syncCycles
      << ",\"rdp_commands\":" << dp.commands
      << ",\"rdp_triangles\":" << dp.triangles
      << ",\"rdp_rectangles\":" << dp.rectangles
      << ",\"rdp_pixels\":" << dp.pixels
      << ",\"rdp_tmem_loads\":" << dp.tmemLoads
      << ",\"rdp_tmem_bytes\":" << dp.tmemBytes
      << ",\"rdp_syncs\":" << dp.syncs
      << ",\"rdram\":{";
    bool first = true;
    for(u32 d = 0; d < (u32)N64::RBusDevice::NUM_RBUS_HW_DEVICES; d++) {
      auto& m = mp.metrics[d];
      if(!first) j << ",";
      first = false;
      j << "\"" << N64::rdram.requestorName((N64::RBusDevice)d) << "\":[" << m.reads << "," << m.writes << "]";
    }
    j << "},\"obs_len\":" << obsLen << ",\"fb\":[" << fbW << "," << fbH << "," << fbBpp << "]"
      << ",\"au_len\":" << auLen << "}\n";
    jsonl << j.str();
    frame++;
    // Sample from the end of frame 0 on, so boot and setup are excluded.
    if(!opt.profile.empty()) N64::cpu.sampler.enabled = true;
  }

  auto writeResult(const std::string& status, u64 fields, double seconds) -> void {
    std::ofstream r(opt.out + "/result.json");
    auto& fp = N64::rdram.footprint;
    r << "{\"status\":\"" << status << "\""
      << ",\"failure\":\"";
    for(char c : failure) { if(c == '"' || c == '\\') r << '\\'; r << c; }
    r << "\",\"frames\":" << frame
      << ",\"vi_fields\":" << fields
      << ",\"footprint_lines\":" << fp.lines()
      << ",\"footprint_bytes\":" << fp.lines() * 16
      << ",\"highest_line\":" << fp.highestLine()
      << ",\"host_seconds\":" << seconds << "}\n";
  }
};

}  // namespace

auto nall::main(Arguments arguments) -> void {
  Runner runner;
  auto& opt = runner.opt;
  string value;
  if(arguments.take("--rom", value)) opt.rom = value;
  if(arguments.take("--replay", value)) opt.replay = value;
  if(arguments.take("--out", value)) opt.out = value;
  if(arguments.take("--frames", value)) opt.frames = value.natural();
  if(arguments.take("--max-fields", value)) opt.maxFields = value.natural();
  if(arguments.take("--profile", value)) { opt.profile = value; N64::cpu.sampler.jitProfile = true; }
  // --idle-range LO:HI (hex virtual addresses, repeatable): CPU time spent
  // executing inside these ranges is reported as cpu_idle_cycles.
  while(arguments.take("--idle-range", value)) {
    auto& s = N64::cpu.sampler;
    auto text = std::string(value);
    auto colon = text.find(':');
    if(colon == std::string::npos || s.idleRanges >= 8) { fprintf(stderr, "bad --idle-range %s\n", text.c_str()); exit(2); }
    s.idleLo[s.idleRanges] = (u32)std::stoul(text.substr(0, colon), nullptr, 16);
    s.idleHi[s.idleRanges] = (u32)std::stoul(text.substr(colon + 1), nullptr, 16);
    s.idleRanges++;
  }
  if(opt.rom.empty() || opt.out.empty() || !opt.frames) {
    fprintf(stderr, "usage: n64run --rom ROM --out DIR --frames N [--replay FILE] [--max-fields N] [--profile FILE] [--idle-range LO:HI ...]\n");
    exit(2);
  }
  if(!opt.maxFields) opt.maxFields = opt.frames * 60 + 600;

  if(!opt.replay.empty()) {
    std::ifstream in(opt.replay);
    if(!in) { fprintf(stderr, "cannot read replay %s\n", opt.replay.c_str()); exit(2); }
    std::string l;
    while(std::getline(in, l)) {
      if(l.empty() || l[0] == '#') continue;
      runner.replay.push_back(parsePad(l));
    }
  }

  directory::create(opt.out.c_str());
  runner.jsonl.open(opt.out + "/frames.jsonl");
  runner.video.open(opt.out + "/video.bin", std::ios::binary);
  runner.audio.open(opt.out + "/audio.bin", std::ios::binary);
  runner.obs.open(opt.out + "/obs.bin", std::ios::binary);

  mia::setHomeLocation([]() -> string { return "/tmp/n64run-home/"; });
  mia::setSaveLocation([]() -> string { return "/tmp/n64run-saves/"; });
  mia::construct();

  ares::platform = &runner;
  runner.systemPak = mia::System::create("Nintendo 64");
  if(runner.systemPak->load() != successful) { fprintf(stderr, "system load failed\n"); exit(3); }
  runner.gamePak = mia::Medium::create("Nintendo 64");
  if(runner.gamePak->load(opt.rom.c_str()) != successful) { fprintf(stderr, "rom load failed\n"); exit(3); }

  N64::option("Enable GPU acceleration", true);
  N64::option("Quality", "SD");
  N64::option("Supersampling", false);
  N64::option("Homebrew Mode", true);
  N64::option("Deterministic Entropy", true);
  N64::option("Recompiler", false);
  N64::option("Expansion Pak", false);

  if(!N64::load(runner.root, "[Nintendo] Nintendo 64 (NTSC)")) { fprintf(stderr, "core load failed\n"); exit(3); }
  if(auto port = runner.root->find<ares::Node::Port>("Cartridge Slot")) { port->allocate(); port->connect(); }
  if(auto port = runner.root->find<ares::Node::Port>("Controller Port 1")) { port->allocate("Gamepad"); port->connect(); }
  runner.root->power();

  // Arm the footprint reset at the ROM's boot address (header bytes 8..11),
  // so RDRAM cleared by the boot loader is not counted against the game.
  {
    std::ifstream rom(opt.rom, std::ios::binary);
    u8 header[12] = {};
    rom.read((char*)header, sizeof(header));
    N64::rdram.footprint.resetPC = header[8] << 24 | header[9] << 16 | header[10] << 8 | header[11];
    N64::rdram.footprint.armed = true;
  }

  auto start = std::chrono::steady_clock::now();
  u64 fields = 0;
  std::string status = "completed";
  while(runner.frame < opt.frames) {
    runner.root->run();
    fields++;
    if(runner.failed) { status = "protocol_error"; break; }
    if(fields >= opt.maxFields) { status = "timeout"; runner.fail("no progress: " + std::to_string(runner.frame) + " frames in " + std::to_string(fields) + " VI fields"); break; }
  }
  double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
  runner.jsonl.close(); runner.video.close(); runner.audio.close(); runner.obs.close();
  runner.writeResult(status, fields, seconds);
  if(!opt.profile.empty()) {
    std::ofstream p(opt.profile);
    p << "# pc samples (1 sample = " << N64::cpu.sampler.interval / 2 << " COUNT ticks)\n";
    for(auto& [pc, n] : N64::cpu.sampler.histogram) p << std::hex << pc << std::dec << " " << n << "\n";
    std::ofstream m(opt.profile + ".dmiss");
    m << "# data-cache misses by faulting PC\n";
    for(auto& [pc, n] : N64::cpu.sampler.dmissPC) m << std::hex << pc << std::dec << " " << n << "\n";
    std::ofstream da(opt.profile + ".dmissaddr");
    da << "# data-cache misses: line address, faulting PC, count\n";
    for(auto& [k, n] : N64::cpu.sampler.dmissAddr) da << std::hex << (u32)(k >> 32) << " " << (u32)k << std::dec << " " << n << "\n";
    std::ofstream wb(opt.profile + ".wb");
    wb << "# data-cache writebacks: physical line, last writer PC, count\n";
    for(auto& [k, n] : N64::cpu.sampler.wbAddr) wb << std::hex << (u32)(k >> 32) << " " << (u32)k << std::dec << " " << n << "\n";
    std::ofstream im(opt.profile + ".imiss");
    im << "# instruction-cache misses by line address\n";
    for(auto& [pc, n] : N64::cpu.sampler.imissPC) im << std::hex << pc << std::dec << " " << n << "\n";
  }
  runner.root->unload();
  exit(status == "completed" ? 0 : 1);
}
