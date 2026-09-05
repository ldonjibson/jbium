# Building Jbium

## Prerequisites

### Hardware Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| CPU cores | 16 | 32-64 (EPYC/Threadripper) |
| RAM | 32GB | 128GB+ |
| Disk space | 200GB | 400GB+ NVMe |
| Disk speed | 500 MB/s | 3+ GB/s (NVMe) |
| OS | Ubuntu 20.04 | Ubuntu 22.04 |

### Build Time Estimates

| Cores | RAM | First Build | Incremental |
|-------|-----|-------------|------------|
| 16 | 32GB | 12-16 hrs | 30-90 min |
| 32 | 64GB | 6-8 hrs | 15-45 min |
| 48 | 96GB | 4-6 hrs | 10-30 min |
| 64 | 128GB | 3-4 hrs | 5-20 min |
| 128 | 256GB | 1.5-2 hrs | 3-10 min |

---

## Quick Start (Vast.ai)

### 1. Launch Instance

```bash
# Find suitable instance
vastai search offers '
    cpu_cores >= 32
    cpu_ram >= 64
    disk_space >= 300
    rentable = true
    order dph_total ASC
'

# Create instance
vastai create instance INSTANCE_ID \
    --image ubuntu:22.04 \
    --disk 300 \
    --ssh
```

### 2. Run Setup

```bash
# Copy setup script
scp scripts/setup.sh root@INSTANCE_IP:/root/

# Run setup (takes ~30 min)
ssh root@INSTANCE_IP
chmod +x /root/setup.sh
nohup bash /root/setup.sh > /root/setup.log 2>&1 &

# Monitor
tail -f /root/setup.log
```

### 3. Build

```bash
# First build (takes hours)
cd /root/jbium/chromium/src
ninja -C out/Release chrome -j$(nproc)

# Monitor progress (separate terminal)
watch -n 5 "ls -la out/Release/chrome 2>/dev/null && echo 'BUILD DONE' || echo 'Still building'"

# Once done, rename the binary (ninja's target is still called "chrome")
mv out/Release/chrome out/Release/jbium
```

---

## Manual Setup (Non-Vast.ai)

### Step 1: Install Dependencies

```bash
sudo apt-get update
sudo apt-get install -y \
    git curl wget \
    build-essential \
    cmake ninja-build \
    pkg-config \
    python3 python3-pip \
    perl bison flex gperf \
    clang lld llvm \
    nodejs npm
```

### Step 2: Install Chromium Dependencies

```bash
sudo apt-get install -y \
    libasound2-dev libatk1.0-dev libatk-bridge2.0-dev \
    libatspi2.0-dev libcairo2-dev libcups2-dev \
    libdrm-dev libgbm-dev libglib2.0-dev libgtk-3-dev \
    libnss3-dev libpango1.0-dev libx11-xcb-dev \
    libxcomposite-dev libxcursor-dev libxdamage-dev \
    libxext-dev libxfixes-dev libxi-dev \
    libxkbcommon-dev libxrandr-dev libxshmfence-dev \
    libxtst-dev libdbus-1-dev
```

### Step 3: Get depot_tools

```bash
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git /opt/depot_tools
echo 'export PATH="/opt/depot_tools:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Step 4: Fetch Source

```bash
mkdir ~/jbium/chromium && cd ~/jbium/chromium
fetch --no-history --nohooks chromium
cd src
```

### Step 5: Run Hooks

```bash
gclient runhooks
```

### Step 6: Configure Build

```bash
mkdir -p out/Release
cp config/args.gn out/Release/args.gn
gn gen out/Release
```

### Step 7: Apply Patches

```bash
bash patches/apply_all.sh
```

### Step 8: Build

```bash
ninja -C out/Release chrome -j$(nproc)

# The ninja target is still named "chrome" (that's Chromium's own build
# target) — rename the resulting binary to jbium:
mv out/Release/chrome out/Release/jbium
```

---

## Applying Patches

Patches are numbered scripts that modify Chromium source code.

```bash
# Apply ALL patches
bash patches/apply_all.sh

# Apply specific patch
bash patches/001_automation/apply.sh

# After patching, rebuild (incremental — only changed files)
ninja -C out/Release chrome -j$(nproc)
```

### Patch Development Workflow

1. Edit the patch script (`patches/XXX_name/apply.sh`)
2. Run the patch: `bash patches/XXX_name/apply.sh`
3. Rebuild: `ninja -C out/Release chrome -j$(nproc)`
4. Test: `python3 scripts/quick_check.py https://bot.sannysoft.com/`
5. If test passes, commit the patch

---

## Testing

### Quick Check

```bash
# Visit one detection site and report
python3 scripts/quick_check.py https://bot.sannysoft.com/
```

### Full Test Suite

```bash
# Run all detection tests
python3 scripts/test_stealth.py

# Run with specific proxy
python3 scripts/test_stealth.py --proxy http://user:pass@proxy:80

# Run headless (not recommended)
python3 scripts/test_stealth.py --headless
```

### Expected Results

| Test | Expected | Meaning |
|------|----------|---------|
| navigator.webdriver | `false` | Automation flag hidden |
| navigator.plugins.length | `5` | Chrome-typical plugins |
| Screen resolution | Matches device profile | Consistent fingerprint |
| Timezone | Matches GeoIP | No IP/location mismatch |
| WebGL renderer | Consumer GPU name | No SwiftShader/llvmpipe |
| Canvas hash | Unique per session | Fingerprint noise working |
| canPlayType("video/mp4") | "probably" | Media codec consistency |

---

## Troubleshooting

### Build Fails

**OOM during linking:**
```
ninja: build stopped: subcommand failed
ld.lld: out of memory
```

Solution: Add swap or use a machine with more RAM.

```bash
sudo fallocate -l 32G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

**Compilation errors after patches:**

Some patches may conflict with Chromium updates. Check which patch failed:

```bash
bash patches/apply_all.sh 2>&1 | grep -i "error"
```

Revert the problematic patch:
```bash
cd /root/jbium/chromium/src
git checkout -- path/to/file
```

### Browser Crashes

Check debug output:
```bash
/root/jbium/chromium/src/out/Release/jbium --no-sandbox \
    --enable-logging --v=1 \
    about:blank 2>&1 | tail -50
```

### Detection Tests Fail

Check if environment variables are set:
```bash
# Browser should show these in the console
/root/jbium/chromium/src/out/Release/jbium --no-sandbox \
    --enable-logging about:blank 2>&1 | grep "STEALTH"
```
