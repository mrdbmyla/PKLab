
local SUBSTRUCT_ORDERS = {
    "GAEM","GAME","GEAM","GEMA","GMAE","GMEA",
    "AGEM","AGME","AEGM","AEMG","AMGE","AMEG",
    "EGAM","EGMA","EAGM","EAMG","EMGA","EMAG",
    "MGAE","MGEA","MAGE","MAEG","MEGA","MEAG",
}

local GEN3_TO_NATIONAL = {
    [277]=252,[278]=253,[279]=254,[280]=255,[281]=256,[282]=257,[283]=258,[284]=259,
    [285]=260,[286]=261,[287]=262,[288]=263,[289]=264,[290]=265,[291]=266,[292]=267,
    [293]=268,[294]=269,[295]=270,[296]=271,[297]=272,[298]=273,[299]=274,[300]=275,
    [301]=290,[302]=291,[303]=292,[304]=276,[305]=277,[306]=285,[307]=286,[308]=327,
    [309]=278,[310]=279,[311]=283,[312]=284,[313]=320,[314]=321,[315]=300,[316]=301,
    [317]=352,[318]=343,[319]=344,[320]=299,[321]=324,[322]=302,[323]=339,[324]=340,
    [325]=370,[326]=341,[327]=342,[328]=349,[329]=350,[330]=318,[331]=319,[332]=328,
    [333]=329,[334]=330,[335]=296,[336]=297,[337]=309,[338]=310,[339]=322,[340]=323,
    [341]=363,[342]=364,[343]=365,[344]=331,[345]=332,[346]=361,[347]=362,[348]=337,
    [349]=338,[350]=298,[351]=325,[352]=326,[353]=311,[354]=312,[355]=303,[356]=307,
    [357]=308,[358]=333,[359]=334,[360]=360,[361]=355,[362]=356,[363]=315,[364]=287,
    [365]=288,[366]=289,[367]=316,[368]=317,[369]=357,[370]=293,[371]=294,[372]=295,
    [373]=366,[374]=367,[375]=368,[376]=359,[377]=353,[378]=354,[379]=336,[380]=335,
    [381]=369,[382]=304,[383]=305,[384]=306,[385]=351,[386]=313,[387]=314,[388]=345,
    [389]=346,[390]=347,[391]=348,[392]=280,[393]=281,[394]=282,[395]=371,[396]=372,
    [397]=373,[398]=374,[399]=375,[400]=376,[401]=377,[402]=378,[403]=379,[404]=382,
    [405]=383,[406]=384,[407]=380,[408]=381,[409]=385,[410]=386,[411]=358,
}

local function gen3ToNational(id)
    if id == nil or id == 0 then return nil end
    if id >= 1 and id <= 251 then return id end
    return GEN3_TO_NATIONAL[id]
end

local function decodeAt(addr)
    local pid = emu:read32(addr)
    if pid == 0 then return nil end
    local otid = emu:read32(addr + 4)
    local storedChecksum = emu:read16(addr + 0x1C)
    local key = (otid ~ pid) & 0xFFFFFFFF

    local sum = 0
    local decWords16 = {}
    for i = 0, 11 do
        local w = emu:read32(addr + 0x20 + i * 4)
        local dw = (w ~ key) & 0xFFFFFFFF
        local lo = dw & 0xFFFF
        local hi = (dw >> 16) & 0xFFFF
        decWords16[i * 2 + 1] = lo
        decWords16[i * 2 + 2] = hi
        sum = (sum + lo + hi) & 0xFFFFFFFF
    end
    if (sum & 0xFFFF) ~= storedChecksum then return nil end

    local order = SUBSTRUCT_ORDERS[(pid % 24) + 1]
    local growthStart = (order:find("G") - 1) * 6
    local miscStart = (order:find("M") - 1) * 6
    local speciesInternal = decWords16[growthStart + 1]
    local species = gen3ToNational(speciesInternal)
    if species == nil then return nil end

    local ivLo = decWords16[miscStart + 3]
    local ivHi = decWords16[miscStart + 4]
    local ivWord = (ivLo | (ivHi << 16)) & 0xFFFFFFFF
    local abilitySlot = (ivWord >> 31) & 1
    local ivs = {
        hp = ivWord & 0x1F,
        atk = (ivWord >> 5) & 0x1F,
        def = (ivWord >> 10) & 0x1F,
        spe = (ivWord >> 15) & 0x1F,
        spa = (ivWord >> 20) & 0x1F,
        spd = (ivWord >> 25) & 0x1F,
    }

    local level = emu:read8(addr + 0x54)
    if level < 1 or level > 100 then return nil end
    local hpCur = emu:read16(addr + 0x56)
    local hpMax = emu:read16(addr + 0x58)
    if hpMax < 1 or hpMax > 2000 then return nil end

    return {
        species = species, level = level, hpCur = hpCur, hpMax = hpMax,
        pid = pid, otid = otid, abilitySlot = abilitySlot, ivs = ivs,
    }
end

local function readParty(baseAddr)
    local party = {}
    for slot = 0, 5 do
        local mon = decodeAt(baseAddr + slot * 100)
        if mon == nil then break end
        table.insert(party, mon)
    end
    return party
end

local GEN3_CONFIG = {
    EMERALD = {
        codePrefix = "BPE",
        sb1PtrAddr = 0x03005D8C, sb2PtrAddr = 0x03005D90, encKeyOffset = 0xAC,
        partyOffset = 0x238, enemyAddr = 0x02024744, moneyOffset = 0x490,
        pocketOffset = {items = 0x560, balls = 0x650},
        pocketSlots  = {items = 30,    balls = 16},
    },
    FIRERED = {
        codePrefix = "BPR",

        sb1PtrAddr = {0x0300378C, 0x03004F58, 0x03005308},
        encKeyOffset = 0xF20,
        partyOffset = 0x38, enemyAddr = 0x0202402C, moneyOffset = 0x290,
        enemyFromParty = -0x258,
        pocketOffset = {items = 0x310, balls = 0x430},
        pocketSlots  = {items = 42,    balls = 13},
    },
    LEAFGREEN = {
        codePrefix = "BPG",
        sb1PtrAddr = {0x0300378C, 0x03004F58, 0x03005308},
        encKeyOffset = 0xF20,
        partyOffset = 0x38, enemyAddr = 0x0202402C, moneyOffset = 0x290,
        enemyFromParty = -0x258,
        pocketOffset = {items = 0x310, balls = 0x430},
        pocketSlots  = {items = 42,    balls = 13},
    },
    RUBY = {
        codePrefix = "AXV",
        sb1Fixed = 0x02025734, enemyAddr = 0x030045C0,
        partyOffset = 0x238, moneyOffset = 0x490, enemyFromParty = 0x260,
        inBattleOffset = 0x43D,
        pocketOffset = {items = 0x560, balls = 0x600},
        pocketSlots  = {items = 20,    balls = 16},
    },
    SAPPHIRE = {
        codePrefix = "AXP",
        sb1Fixed = 0x02025734, enemyAddr = 0x030045C0,
        partyOffset = 0x238, moneyOffset = 0x490, enemyFromParty = 0x260,
        inBattleOffset = 0x43D,
        pocketOffset = {items = 0x560, balls = 0x600},
        pocketSlots  = {items = 20,    balls = 16},
    },
}

local gMainAddr = nil
local gMainProbe = nil
local GMAIN_PROBE_FRAMES = 10
local gMainNextProbe = 0

local function isRomPtr(v)
    return v >= 0x08000000 and v < 0x0A000000
end

local function probeGMain(frame)
    if gMainAddr then return end
    if gMainProbe == nil then
        if frame < gMainNextProbe then return end
        local cands = {}
        for a = 0x03000000, 0x03007800, 4 do
            local cb1, vbl = emu:read32(a), emu:read32(a + 0x0C)
            if isRomPtr(emu:read32(a + 4)) and (cb1 == 0 or isRomPtr(cb1)) and (vbl == 0 or isRomPtr(vbl)) then
                cands[a] = {emu:read32(a + 0x20), emu:read32(a + 0x24)}
            end
        end
        gMainProbe = {frame = frame, cands = cands}
        return
    end
    local elapsed = frame - gMainProbe.frame
    if elapsed < GMAIN_PROBE_FRAMES then return end

    local both, secondOnly = {}, {}
    for a, v in pairs(gMainProbe.cands) do
        local d1 = (emu:read32(a + 0x20) - v[1]) & 0xFFFFFFFF
        local d2 = (emu:read32(a + 0x24) - v[2]) & 0xFFFFFFFF
        if d2 >= elapsed - 1 and d2 <= elapsed + 1 then
            if d1 == d2 then
                table.insert(both, a)
            elseif d1 == 0 then
                table.insert(secondOnly, a)
            end
        end
    end
    gMainProbe = nil
    local found = #both > 0 and both or secondOnly
    if #found == 1 then gMainAddr = found[1] else gMainNextProbe = frame + 120 end
end

local function inBattle(cfg)
    if not gMainAddr or not cfg then return nil end
    return ((emu:read8(gMainAddr + (cfg.inBattleOffset or 0x439)) >> 1) & 1) == 1
end

local function currentConfig()
    local code = emu:getGameCode() or ""
    for _, cfg in pairs(GEN3_CONFIG) do
        if code:find(cfg.codePrefix, 1, true) then return cfg end
    end
    return nil
end

local sb1Hist, sb1Pick = nil, nil
local function resolveSaveBlock1(cfg)
    if cfg.sb1Fixed then return cfg.sb1Fixed end
    if type(cfg.sb1PtrAddr) == "number" then
        return emu:read32(cfg.sb1PtrAddr)
    end

    sb1Hist = sb1Hist or {}
    for _, ptrAddr in ipairs(cfg.sb1PtrAddr) do
        local v = emu:read32(ptrAddr)
        if v >= 0x02000000 and v < 0x0203C000 then
            local sig = emu:read32(v) .. ":" .. emu:read16(v + 4)
            if sb1Hist[v] ~= nil and sb1Hist[v] ~= sig then sb1Pick = v end
            sb1Hist[v] = sig
        end
    end
    if sb1Pick then
        for _, ptrAddr in ipairs(cfg.sb1PtrAddr) do
            if emu:read32(ptrAddr) == sb1Pick then return sb1Pick end
        end
    end

    for _, ptrAddr in ipairs(cfg.sb1PtrAddr) do
        local v = emu:read32(ptrAddr)
        if decodeAt(v + cfg.partyOffset) ~= nil then
            return v
        end
    end

    for _, ptrAddr in ipairs(cfg.sb1PtrAddr) do
        local v = emu:read32(ptrAddr)
        if v >= 0x02000000 and v < 0x0203C000 then
            local x, y = emu:read16(v), emu:read16(v + 2)
            if x < 1000 and y < 1000 and emu:read8(v + 4) <= 42 and (x > 0 or y > 0) then
                return v
            end
        end
    end
    return emu:read32(cfg.sb1PtrAddr[1])
end

local lastGoodOffset = 0x238

local FIXED_PLAYER_ADDR = 0x020244EC

local function findPlayerPartyRaw(saveBlock1)
    local party = readParty(FIXED_PLAYER_ADDR)
    if #party > 0 then return party end
    party = readParty(saveBlock1 + lastGoodOffset)
    if #party > 0 then return party end
    for off = 0x200, 0x280, 4 do
        if off ~= lastGoodOffset then
            party = readParty(saveBlock1 + off)
            if #party > 0 then
                lastGoodOffset = off
                return party
            end
        end
    end
    return {}
end

local lastKnownGoodParty = {}
local emptyStreak = 0
local EMPTY_STREAK_TO_CLEAR = 4

local function findPlayerParty(saveBlock1)
    local party = findPlayerPartyRaw(saveBlock1)
    if #party > 0 then
        lastKnownGoodParty = party
        emptyStreak = 0
        return party
    end
    emptyStreak = emptyStreak + 1
    if emptyStreak >= EMPTY_STREAK_TO_CLEAR then
        lastKnownGoodParty = {}
        return {}
    end
    return lastKnownGoodParty
end

local SAVEBLOCK1_SIZE = 0x4000
local livePartyAddr = nil
local lastLivePartySearch = -1000

local function findLiveParty(cfg, saveBlock1)
    if livePartyAddr and decodeAt(livePartyAddr) then return livePartyAddr end
    livePartyAddr = nil

    if os.clock() - lastLivePartySearch < 2 then return nil end
    lastLivePartySearch = os.clock()
    local pids = {}
    for _, mon in ipairs(readParty(saveBlock1 + cfg.partyOffset)) do pids[mon.pid] = true end
    if next(pids) == nil then

        if cfg.enemyAddr and cfg.enemyFromParty then
            local a = cfg.enemyAddr - cfg.enemyFromParty
            if decodeAt(a) then
                livePartyAddr = a
                return a
            end
        end
        return nil
    end
    local function inSave(a) return a >= saveBlock1 and a < saveBlock1 + SAVEBLOCK1_SIZE end
    for _, range in ipairs({{0x02000000, 0x0203FF9C}, {0x03000000, 0x03007F9C}}) do
        for a = range[1], range[2], 4 do
            if pids[emu:read32(a)] and not inSave(a) and decodeAt(a) then
                local prev = decodeAt(a - 100)
                if not (prev and pids[prev.pid]) then
                    livePartyAddr = a
                    return a
                end
            end
        end
    end
    return nil
end

local GEN3_CHEATS = {
    master_ball = {kind = "items", list = {{item = 1,  qty = 999, pocket = "balls"}}},
    rare_candy  = {kind = "items", list = {{item = 68, qty = 999, pocket = "items"}}},
    money       = {kind = "money"},
}
local MAX_MONEY = 999999
local CHEAT_REQUEST_PATH = "C:/pkmn/gen3_cheat_request.txt"
local CHEAT_RESULT_PATH = "C:/pkmn/gen3_cheat_result.txt"

local function checkKeyCandidate(cfg, saveBlock1, keyLo)
    local base = saveBlock1 + cfg.pocketOffset.items
    for i = 0, cfg.pocketSlots.items - 1 do
        local addr = base + i * 4
        local id = emu:read16(addr)
        local plain = emu:read16(addr + 2) ~ keyLo
        if id == 0 then
            if plain ~= 0 then return false end
        elseif plain < 1 or plain > 99 then
            return false
        end
    end
    return true
end

local function resolveKey(cfg, saveBlock1)
    if checkKeyCandidate(cfg, saveBlock1, 0) then return 0 end
    if not cfg.encKeyOffset then
        return nil
    end
    if cfg.sb2PtrAddr then
        local saveBlock2 = emu:read32(cfg.sb2PtrAddr)
        local key = emu:read32(saveBlock2 + cfg.encKeyOffset)
        if checkKeyCandidate(cfg, saveBlock1, key & 0xFFFF) then return key end
    end
    for addr = 0x03000000, 0x03007FFC, 4 do
        local v = emu:read32(addr)
        if v >= 0x02000000 and v < 0x02040000 then
            local key = emu:read32(v + cfg.encKeyOffset)
            if checkKeyCandidate(cfg, saveBlock1, key & 0xFFFF) then return key end
        end
    end
    return nil
end

local function giveBagItem(cfg, saveBlock1, keyLo, pocketName, itemId, addQty)
    local base = saveBlock1 + cfg.pocketOffset[pocketName]
    for i = 0, cfg.pocketSlots[pocketName] - 1 do
        local addr = base + i * 4
        local id = emu:read16(addr)
        local rawQty = emu:read16(addr + 2)
        if id == itemId then
            local plain = (rawQty ~ keyLo) + addQty
            if plain > 99 then plain = 99 end
            emu:write16(addr + 2, plain ~ keyLo)
            return true, plain
        end
        if id == 0 and rawQty == keyLo then
            local plain = addQty
            if plain > 99 then plain = 99 end
            emu:write16(addr, itemId)
            emu:write16(addr + 2, plain ~ keyLo)
            return true, plain
        end
    end
    return false
end

local function giveMoney(cfg, saveBlock1, key)
    if not cfg.moneyOffset then return false end
    local addr = saveBlock1 + cfg.moneyOffset
    emu:write32(addr, MAX_MONEY ~ key)
    return true
end

local function runCheat(cheatKey)
    local cfg = currentConfig()
    if not cfg then
        return false, "jeu non pris en charge"
    end
    local spec = GEN3_CHEATS[cheatKey]
    if not spec then return false, "triche inconnue" end
    local saveBlock1 = resolveSaveBlock1(cfg)
    local key = resolveKey(cfg, saveBlock1)
    if key == nil then
        return false, "sac non localisé (vérifie que la partie est bien chargée)"
    end
    if spec.kind == "money" then
        if not giveMoney(cfg, saveBlock1, key) then
            return false, "argent non configuré pour ce jeu"
        end
        return true, tostring(MAX_MONEY)
    end
    local keyLo = key & 0xFFFF
    local report = {}
    for _, it in ipairs(spec.list) do
        local ok, newQty = giveBagItem(cfg, saveBlock1, keyLo, it.pocket, it.item, it.qty)
        if not ok then
            return false, "sac plein"
        end
        table.insert(report, it.item .. ":" .. newQty)
    end
    return true, table.concat(report, ",")
end

local function checkCheatRequest()
    local f = io.open(CHEAT_REQUEST_PATH, "r")
    if not f then return end
    local cheatKey = f:read("*l")
    f:close()
    os.remove(CHEAT_REQUEST_PATH)
    if not cheatKey then return end
    cheatKey = cheatKey:gsub("%s+", "")

    local ok, result, detail = pcall(runCheat, cheatKey)
    local out
    if not ok then
        out = "error:" .. tostring(result)
    elseif result then
        out = "ok:" .. tostring(detail or "")
    else
        out = "error:" .. tostring(detail or "échec")
    end
    local rf = io.open(CHEAT_RESULT_PATH, "w")
    if rf then
        rf:write(out)
        rf:close()
    end
end

local function writeSnapshot()
    local ok, err = pcall(function()
        local cfg = currentConfig()
        local saveBlock1 = 0
        local player, enemy = {}, {}
        local enemyAddr = nil
        if cfg then
            saveBlock1 = resolveSaveBlock1(cfg)
            enemyAddr = cfg.enemyAddr
            if cfg.codePrefix == "BPE" then

                player = findPlayerParty(saveBlock1)
            else
                local live = findLiveParty(cfg, saveBlock1)
                player = readParty(live or (saveBlock1 + cfg.partyOffset))
                if live and cfg.enemyFromParty then
                    enemyAddr = live + cfg.enemyFromParty
                end
            end

            if inBattle(cfg) ~= false then
                enemy = readParty(enemyAddr)
            end
        end

        local parts = {}
        table.insert(parts, '"game":"' .. (emu:getGameCode() or "?") .. '"')

        if cfg then
            local posX = emu:read16(saveBlock1 + 0x00)
            local posY = emu:read16(saveBlock1 + 0x02)
            local mapGroup = emu:read8(saveBlock1 + 0x04)
            local mapNum = emu:read8(saveBlock1 + 0x05)
            if posX >= 0x8000 then posX = posX - 0x10000 end
            if posY >= 0x8000 then posY = posY - 0x10000 end
            table.insert(parts, string.format('"pos":{"x":%d,"y":%d,"mapGroup":%d,"mapNum":%d}', posX, posY, mapGroup, mapNum))
        end

        local function partyJson(party)
            local items = {}
            for _, mon in ipairs(party) do
                table.insert(items, string.format(
                    '{"species":%d,"level":%d,"hpCur":%d,"hpMax":%d,"pid":%d,"otid":%d,"abilitySlot":%d,"ivs":{"hp":%d,"atk":%d,"def":%d,"spa":%d,"spd":%d,"spe":%d}}',
                    mon.species, mon.level, mon.hpCur, mon.hpMax, mon.pid, mon.otid, mon.abilitySlot,
                    mon.ivs.hp, mon.ivs.atk, mon.ivs.def, mon.ivs.spa, mon.ivs.spd, mon.ivs.spe
                ))
            end
            return "[" .. table.concat(items, ",") .. "]"
        end

        table.insert(parts, '"player":' .. partyJson(player))
        table.insert(parts, '"enemy":' .. partyJson(enemy))
        local json = "{" .. table.concat(parts, ",") .. "}"

        local f = io.open("C:/pkmn/gen3_raw.json", "w")
        if f then
            f:write(json)
            f:close()
        end
    end)
    if not ok then
        console:log("Error: " .. tostring(err))
    end
end

local frameCount = 0
local lastWrite = -1
callbacks:add("frame", function()
    frameCount = frameCount + 1
    pcall(probeGMain, frameCount)
    if frameCount % 15 == 0 then
        local now = os.clock()
        if now - lastWrite >= 0.2 then
            lastWrite = now
            writeSnapshot()
            checkCheatRequest()
        end
    end
end)

console:log("Gen3 bridge loaded. Writing C:/pkmn/gen3_raw.json ~4x/sec.")
writeSnapshot()
