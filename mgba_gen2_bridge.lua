
local GAMES = {
    PM_CRYSTAL = {
        key = "CRYSTAL",
        partyCount = 0xDCD7, otPartyCount = 0xD280, curOTMon = 0xC663, enemyMon = 0xD206,
        battleMode = 0xD22D, mapGroup = 0xDCB5, money = 0xD84E, numItems = 0xD892, numBalls = 0xD8D7, timeOfDay = 0xD269,
    },
    POKEMON_GLD = {
        key = "GOLD",
        partyCount = 0xDA22, otPartyCount = 0xDD55, curOTMon = 0xCB41, enemyMon = 0xD0EF,
        battleMode = 0xD116, mapGroup = 0xDA00, money = 0xD573, numItems = 0xD5B7, numBalls = 0xD5FC, timeOfDay = 0xD157,
    },
}
GAMES.POKEMON_SLV = {}
for k, v in pairs(GAMES.POKEMON_GLD) do GAMES.POKEMON_SLV[k] = v end
GAMES.POKEMON_SLV.key = "SILVER"

local POCKETS = {items = {field = "numItems", cap = 20}, balls = {field = "numBalls", cap = 12}}
local CHEATS = {
    master_ball = {pocket = "balls", item = 1},
    rare_candy = {pocket = "items", item = 0x20},
    money = {money = true},
}
local MAX_MONEY = 999999
local OUT_PATH = "C:/pkmn/gen3_raw.json"
local CHEAT_REQUEST_PATH = "C:/pkmn/gen3_cheat_request.txt"
local CHEAT_RESULT_PATH = "C:/pkmn/gen3_cheat_result.txt"
local MON_SIZE = 48

local wram = nil
local cfg = nil

local function r8(addr) return wram:read8(addr - 0xC000) end
local function w8(addr, v) wram:write8(addr - 0xC000, v & 0xFF) end
local function r16(addr) return (r8(addr) << 8) | r8(addr + 1) end

local function currentConfig()
    local title = (emu:getGameTitle() or ""):gsub("%z", ""):gsub("%s+$", "")
    for prefix, c in pairs(GAMES) do
        if title:sub(1, #prefix) == prefix then return c end
    end
    return nil
end

local function speciesListOk(countAddr)
    local n = r8(countAddr)
    if n < 1 or n > 6 then return false end
    for i = 1, n do
        local s = r8(countAddr + i)
        if s < 1 or s > 251 then return false end
    end
    if r8(countAddr + n + 1) ~= 0xFF then return false end
    local first = countAddr + 8
    for i = 0, n - 1 do
        local m = first + i * MON_SIZE
        if r8(m) ~= r8(countAddr + 1 + i) then return false end
        local lv = r8(m + 0x1F)
        if lv < 1 or lv > 100 then return false end
    end
    return true
end

local function readMon(addr, battle)
    local species, level, hp, hpMax, dvA, dvB, otid, item
    species = r8(addr)
    if species < 1 or species > 251 then return nil end
    item = r8(addr + 1)
    if battle then
        dvA, dvB = r8(addr + 6), r8(addr + 7)
        level, hp, hpMax = r8(addr + 13), r16(addr + 16), r16(addr + 18)
        otid = -1
    else
        otid = r16(addr + 6)
        dvA, dvB = r8(addr + 21), r8(addr + 22)
        level, hp, hpMax = r8(addr + 0x1F), r16(addr + 0x22), r16(addr + 0x24)
    end
    if level < 1 or level > 100 or hpMax < 1 or hpMax > 999 or hp > hpMax then return nil end
    return string.format('{"species":%d,"level":%d,"hpCur":%d,"hpMax":%d,"otid":%d,"item":%d,"dv":{"atk":%d,"def":%d,"spe":%d,"spc":%d}}',
        species, level, hp, hpMax, otid, item, dvA >> 4, dvA & 15, dvB >> 4, dvB & 15)
end

local function readParty(countAddr)
    local out = {}
    if not speciesListOk(countAddr) then return out end
    for i = 0, r8(countAddr) - 1 do
        local m = readMon(countAddr + 8 + i * MON_SIZE, false)
        if not m then return {} end
        table.insert(out, m)
    end
    return out
end

local function readEnemy()
    local mode = r8(cfg.battleMode)
    if mode ~= 1 and mode ~= 2 then return {}, nil end
    local active = readMon(cfg.enemyMon, true)
    if mode == 1 then
        return active and {active} or {}, "wild"
    end
    local party = {}
    local n = r8(cfg.otPartyCount)
    if n < 1 or n > 6 then return active and {active} or {}, "trainer" end
    local cur = wram:read8(cfg.curOTMon - 0xC000)
    for i = 0, n - 1 do
        local m
        if i == cur and active then m = active else m = readMon(cfg.otPartyCount + 8 + i * MON_SIZE, false) end
        if m then table.insert(party, m) end
    end
    return party, "trainer"
end

local function giveItem(pocketName, itemId)
    local p = POCKETS[pocketName]
    local countAddr = cfg[p.field]
    local n = r8(countAddr)
    if n > p.cap then return false, "sac non localisé (vérifie que la partie est bien chargée)" end
    for i = 0, n - 1 do
        if r8(countAddr + 1 + i * 2) == itemId then
            w8(countAddr + 2 + i * 2, 99)
            return true
        end
    end
    if n >= p.cap then return false, "sac plein" end
    w8(countAddr + 1 + n * 2, itemId)
    w8(countAddr + 2 + n * 2, 99)
    w8(countAddr + 3 + n * 2, 0xFF)
    w8(countAddr, n + 1)
    return true
end

local function runCheat(cheatKey)
    if not cfg then return false, "jeu non pris en charge" end
    local spec = CHEATS[cheatKey]
    if not spec then return false, "triche inconnue" end
    if not speciesListOk(cfg.partyCount) then return false, "partie non chargée" end
    if spec.money then
        w8(cfg.money, MAX_MONEY >> 16)
        w8(cfg.money + 1, MAX_MONEY >> 8)
        w8(cfg.money + 2, MAX_MONEY)
        return true, tostring(MAX_MONEY)
    end
    return giveItem(spec.pocket, spec.item)
end

local function checkCheatRequest()
    local f = io.open(CHEAT_REQUEST_PATH, "r")
    if not f then return end
    local cheatKey = f:read("*l")
    f:close()
    os.remove(CHEAT_REQUEST_PATH)
    if not cheatKey then return end
    local ok, result, detail = pcall(runCheat, (cheatKey:gsub("%s+", "")))
    local out
    if not ok then out = "error:" .. tostring(result)
    elseif result then out = "ok:" .. tostring(detail or "")
    else out = "error:" .. tostring(detail or "échec") end
    local rf = io.open(CHEAT_RESULT_PATH, "w")
    if rf then rf:write(out) rf:close() end
end

local function writeSnapshot()
    cfg = currentConfig()
    wram = emu.memory and emu.memory.wram
    local parts = {}
    if cfg and wram then
        local player = readParty(cfg.partyCount)
        local enemy, kind = readEnemy()
        table.insert(parts, '"game":"GEN2:' .. cfg.key .. '"')
        table.insert(parts, '"gen":2')
        if #player > 0 then
            table.insert(parts, string.format('"pos":{"x":%d,"y":%d,"mapGroup":%d,"mapNum":%d}',
                r8(cfg.mapGroup + 3), r8(cfg.mapGroup + 2), r8(cfg.mapGroup), r8(cfg.mapGroup + 1)))
        end
        table.insert(parts, '"tod":' .. r8(cfg.timeOfDay))
        table.insert(parts, '"battle":' .. (kind and ('"' .. kind .. '"') or "null"))
        table.insert(parts, '"player":[' .. table.concat(player, ",") .. "]")
        table.insert(parts, '"enemy":[' .. table.concat(enemy, ",") .. "]")
    else
        table.insert(parts, '"game":"?"')
        table.insert(parts, '"player":[]')
        table.insert(parts, '"enemy":[]')
    end
    local f = io.open(OUT_PATH, "w")
    if f then
        f:write("{" .. table.concat(parts, ",") .. "}")
        f:close()
    end
end

local frameCount = 0
local lastWrite = -1
callbacks:add("frame", function()
    frameCount = frameCount + 1
    if frameCount % 15 == 0 then
        local now = os.clock()
        if now - lastWrite >= 0.2 then
            lastWrite = now
            local ok, err = pcall(writeSnapshot)
            if not ok then console:log("Error: " .. tostring(err)) end
            pcall(checkCheatRequest)
        end
    end
end)

console:log("Gen2 bridge loaded.")
