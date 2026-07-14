local function cap(name, ...) DSTLAB_NATIVE("DSTLab.Runtime.Event", name, ...) end
local function Vector3(x,y,z) return {x=x or 0,y=y or 0,z=z or 0,Get=function(s)return s.x,s.y,s.z end} end
GLOBAL.Vector3 = GLOBAL.Vector3 or Vector3
GLOBAL.BRANCH = GLOBAL.BRANCH or "release"
GLOBAL.PLATFORM = GLOBAL.PLATFORM or "WIN32_STEAM"
GLOBAL.IsConsole = GLOBAL.IsConsole or function() return false end
if GLOBAL.hash == nil then
 GLOBAL.hash = function(value)
  local text = tostring(value)
  local result = 5381
  for i = 1, #text do result = (result * 33 + string.byte(text, i)) % 2147483647 end
  cap("fixture.hash", text, result)
  return result
 end
end

if GLOBAL.Asset==nil then GLOBAL.Asset=function(kind,file,param) cap("construct.Asset",kind,file); return {type=kind,file=file,param=param} end end
function GLOBAL.Ingredient(prefab,amount,atlas) cap("construct.Ingredient",prefab,amount); return {type=prefab,amount=amount,atlas=atlas} end
if GLOBAL.Prefab==nil then GLOBAL.Prefab=function(name,fn,assets,deps,force) cap("construct.Prefab",name); return {name=name,fn=fn,assets=assets or {},deps=deps or {},force_path_search=force} end end
function GLOBAL.Recipe(name,ingredients,tab,tech,placer,min_spacing,nounlock,numtogive,builder_tag,atlas,image,testfn,product)
 cap("construct.Recipe",name); return {name=name,ingredients=ingredients or {},tab=tab,level=tech,placer=placer,min_spacing=min_spacing,nounlock=nounlock,numtogive=numtogive,builder_tag=builder_tag,atlas=atlas,image=image,testfn=testfn,product=product or name}
end
function GLOBAL.Action(data) data=data or {}; if data.fn==nil then data.fn=function()return false end end; cap("construct.Action",data.id); return data end
function GLOBAL.State(data) cap("construct.State",data and data.name); return data or {} end
function GLOBAL.StateGraph(name,states,events,initial,handlers) cap("construct.StateGraph",name); return {name=name,states=states or {},events=events or {},initialstate=initial,actionhandlers=handlers or {}} end
function GLOBAL.EventHandler(name,fn) cap("construct.EventHandler",name); return {name=name,fn=fn} end
function GLOBAL.TimeEvent(time,fn) cap("construct.TimeEvent",time); return {time=time,fn=fn} end
function GLOBAL.ActionHandler(action,dest) cap("construct.ActionHandler",action and action.id); return {action=action,deststate=dest} end

if GLOBAL.Class==nil then
 function GLOBAL.Class(base,ctor)
  if ctor==nil and type(base)=="function" then ctor,base=base,nil end
  local c={}; c.__index=c; c._ctor=ctor
  setmetatable(c,{__index=base,__call=function(k,...)local o=setmetatable({},k); if base and base._ctor then base._ctor(o,...) end; if ctor then ctor(o,...) end; return o end})
  cap("construct.Class"); return c
 end
end
GLOBAL.TECH=GLOBAL.TECH or {}; GLOBAL.TECH.NONE=GLOBAL.TECH.NONE or {}; GLOBAL.RECIPETABS=GLOBAL.RECIPETABS or {}; GLOBAL.ACTIONS=GLOBAL.ACTIONS or {}

GLOBAL.MOD_RPC=GLOBAL.MOD_RPC or {}; GLOBAL.CLIENT_MOD_RPC=GLOBAL.CLIENT_MOD_RPC or {}; GLOBAL.SHARD_MOD_RPC=GLOBAL.SHARD_MOD_RPC or {}
local function rpc(add,get,registry,kind)
 local original=GLOBAL[add]
 GLOBAL[add]=function(ns,name,fn) registry[ns]=registry[ns] or {}; local id={namespace=ns,name=name,id=ns.."."..name,kind=kind}; registry[ns][name]=id; cap("rpc_identity.register",kind,ns,name); if original then original(ns,name,fn) end; return id end
 if env then env[add]=GLOBAL[add] end
 GLOBAL[get]=function(ns,name) cap("rpc_identity.get",kind,ns,name); return registry[ns] and registry[ns][name] or nil end
end
rpc("AddModRPCHandler","GetModRPC",GLOBAL.MOD_RPC,"server"); rpc("AddClientModRPCHandler","GetClientModRPC",GLOBAL.CLIENT_MOD_RPC,"client"); rpc("AddShardModRPCHandler","GetShardModRPC",GLOBAL.SHARD_MOD_RPC,"shard")

local nextguid=1000
local EntityScript=GLOBAL.EntityScript
if type(EntityScript)~="table" then EntityScript={}; EntityScript.__index=EntityScript; GLOBAL.EntityScript=EntityScript end
local function subsystem(inst,name)
 local o={inst=inst,_fixture=name}
 if name=="Transform" then
  o.x,o.y,o.z,o.rotation=0,0,0,0
  function o:SetPosition(x,y,z) self.x,self.y,self.z=x or 0,y or 0,z or 0; cap("transform.SetPosition",inst.GUID,self.x,self.y,self.z) end
  function o:GetWorldPosition() return self.x,self.y,self.z end
  function o:SetRotation(v) self.rotation=v or 0; cap("transform.SetRotation",inst.GUID,self.rotation) end
  function o:GetRotation() return self.rotation end
  function o:SetScale(x,y,z) self.scale={x or 1,y or 1,z or 1}; cap("transform.SetScale",inst.GUID,x,y,z) end
 elseif name=="AnimState" then
  function o:SetBank(v) self.bank=v; cap("anim.SetBank",inst.GUID,v) end
  function o:SetBuild(v) self.build=v; cap("anim.SetBuild",inst.GUID,v) end
  function o:PlayAnimation(v,loop) self.animation=v; self.loop=loop==true; cap("anim.PlayAnimation",inst.GUID,v,loop) end
  function o:PushAnimation(v,loop) self.queued=v; cap("anim.PushAnimation",inst.GUID,v,loop) end
  function o:SetPercent(v,p) self.animation,self.percent=v,p; cap("anim.SetPercent",inst.GUID,v,p) end
  function o:OverrideSymbol(s,b,f) self.overrides=self.overrides or {}; self.overrides[s]={b,f}; cap("anim.OverrideSymbol",inst.GUID,s) end
  function o:Hide(s) self.hidden=self.hidden or {}; self.hidden[s]=true; cap("anim.Hide",inst.GUID,s) end
  function o:Show(s) if self.hidden then self.hidden[s]=nil end; cap("anim.Show",inst.GUID,s) end
 elseif name=="Network" then
  function o:SetPristine() self.pristine=true; cap("network.SetPristine",inst.GUID) end
  function o:SetClassifiedTarget(t) self.target=t; cap("network.SetClassifiedTarget",inst.GUID,t and t.GUID) end
 elseif name=="SoundEmitter" then
  function o:PlaySound(sound,handle) self.playing=self.playing or {}; if handle then self.playing[handle]=sound end; cap("sound.PlaySound",inst.GUID,sound,handle) end
  function o:KillSound(handle) if self.playing then self.playing[handle]=nil end; cap("sound.KillSound",inst.GUID,handle) end
  function o:PlayingSound(handle) return self.playing~=nil and self.playing[handle]~=nil end
 elseif name=="Light" then
  function o:Enable(v) self.enabled=v==true; cap("light.Enable",inst.GUID,v) end
  function o:SetRadius(v) self.radius=v; cap("light.SetRadius",inst.GUID,v) end
  function o:SetIntensity(v) self.intensity=v; cap("light.SetIntensity",inst.GUID,v) end
  function o:SetColour(r,g,b) self.colour={r,g,b}; cap("light.SetColour",inst.GUID) end
 elseif name=="Physics" then
  function o:SetMass(v) self.mass=v; cap("physics.SetMass",inst.GUID,v) end
  function o:SetCapsule(r,h) self.capsule={r,h}; cap("physics.SetCapsule",inst.GUID,r,h) end
  function o:SetCollisionGroup(v) self.group=v; cap("physics.SetCollisionGroup",inst.GUID,v) end
  function o:CollidesWith(v) self.collides=self.collides or {}; self.collides[v]=true; cap("physics.CollidesWith",inst.GUID,v) end
  function o:ClearCollisionMask() self.collides={}; cap("physics.ClearCollisionMask",inst.GUID) end
 end
 return o
end
local systems={"Transform","AnimState","Network","SoundEmitter","Light","Physics"}
for _,name in ipairs(systems) do EntityScript["Add"..name]=EntityScript["Add"..name] or function(self) if self[name]==nil then self[name]=subsystem(self,name); cap("entity.Add"..name,self.GUID) end; return self[name] end end
function EntityScript:AddTag(tag) self.tags[tag]=true; cap("entity.AddTag",self.GUID,tag) end
function EntityScript:RemoveTag(tag) self.tags[tag]=nil; cap("entity.RemoveTag",self.GUID,tag) end
function EntityScript:HasTag(tag) return self.tags[tag]==true end
function EntityScript:AddComponent(name) local c={inst=self,_fixture=name}; self.components[name]=c; cap("entity.AddComponent",self.GUID,name); return c end
function EntityScript:RemoveComponent(name) self.components[name]=nil; cap("entity.RemoveComponent",self.GUID,name) end
function EntityScript:GetComponent(name) return self.components[name] end
function EntityScript:ListenForEvent(name,fn,source) self._listeners[name]=self._listeners[name] or {}; table.insert(self._listeners[name],{fn=fn,source=source}); cap("entity.ListenForEvent",self.GUID,name) end
function EntityScript:PushEvent(name,data) cap("entity.PushEvent",self.GUID,name); for _,v in ipairs(self._listeners[name] or {}) do v.fn(self,data) end end
function EntityScript:IsValid() return not self._removed end
function EntityScript:Remove() self._removed=true; cap("entity.Remove",self.GUID) end
function EntityScript:GetPosition() if self.Transform then local x,y,z=self.Transform:GetWorldPosition(); return Vector3(x,y,z) end; return Vector3() end

function GLOBAL.CreateEntity()
 nextguid=nextguid+1; local inst=setmetatable({GUID=nextguid,tags={},components={},_listeners={},entity={}},EntityScript)
 for _,name in ipairs(systems) do inst.entity["Add"..name]=function() return inst["Add"..name](inst) end end
 if GLOBAL.DSTLAB_ATTACH_SCHEDULER then GLOBAL.DSTLAB_ATTACH_SCHEDULER(inst) end
 cap("entity.CreateEntity",inst.GUID); return inst
end
function GLOBAL.SpawnPrefab(name) local i=GLOBAL.CreateEntity(); i.prefab=name; cap("entity.SpawnPrefab",name,i.GUID); return i end

local world={ismastersim=true,ismastershard=true,tags={},state={},GUID=1}
function world:AddTag(t) self.tags[t]=true; cap("world.AddTag",t) end
function world:RemoveTag(t) self.tags[t]=nil; cap("world.RemoveTag",t) end
function world:HasTag(t) return self.tags[t]==true end
GLOBAL.TheWorld=world
local original_net = GLOBAL.TheNet
local net_fixture = {
 GetIsDedicated=function()cap("net.GetIsDedicated");return false end,
 IsDedicated=function()cap("net.IsDedicated");return false end,
 GetIsServer=function()cap("net.GetIsServer");return true end,
 GetIsClient=function()cap("net.GetIsClient");return false end,
 GetIsServerAdmin=function()cap("net.GetIsServerAdmin");return false end,
 GetServerIsClientHosted=function()cap("net.GetServerIsClientHosted");return true end,
 GetServerGameMode=function()cap("net.GetServerGameMode");return "survival" end,
 GetUserID=function()cap("net.GetUserID");return GLOBAL.DSTLAB_USERID or "KU_OFFLINE" end,
}
-- Keep unknown calls on the strict native proxy so missing engine APIs remain
-- visible in unsupported.json instead of degrading into silent nil values.
if original_net ~= nil then setmetatable(net_fixture, {__index=original_net}) end
GLOBAL.TheNet=net_fixture
GLOBAL.TheInput={IsKeyDown=function(_,k)cap("input.IsKeyDown",k);return false end,IsControlPressed=function(_,c)cap("input.IsControlPressed",c);return false end,ControllerAttached=function()cap("input.ControllerAttached");return false end,GetWorldPosition=function()cap("input.GetWorldPosition");return Vector3() end,GetScreenPosition=function()cap("input.GetScreenPosition");return Vector3() end,GetHUDEntityUnderMouse=function()cap("input.GetHUDEntityUnderMouse");return nil end}
local front={_screens={}}; function front:GetActiveScreen()return self._screens[#self._screens] end; function front:GetFocusWidget()cap("frontend.GetFocusWidget");return nil end; function front:PushScreen(s)table.insert(self._screens,s);cap("frontend.PushScreen")end; function front:PopScreen()local s=table.remove(self._screens);cap("frontend.PopScreen");return s end; GLOBAL.TheFrontEnd=front

-- Read-only io.open limited by the host handler to the selected MOD and its
-- declared dependency roots. Write/append modes and unrelated host paths are
-- rejected. The object implements only the common read/lines/seek/close API.
io.open = function(path, mode)
 local data, err = DSTLAB_NATIVE("DSTLab.Runtime.ReadFile", path, mode or "r")
 if data == nil then return nil, err end
 local file = {data=data, pos=1, closed=false}
 function file:read(format)
  if self.closed then return nil, "file is closed" end
  format = format or "*l"
  if format == "*a" then local out=string.sub(self.data,self.pos); self.pos=#self.data+1; return out end
  if format == "*l" then
   if self.pos > #self.data then return nil end
   local start, finish = string.find(self.data, "\n", self.pos, true)
   local out
   if start == nil then out=string.sub(self.data,self.pos); self.pos=#self.data+1
   else out=string.sub(self.data,self.pos,start-1); self.pos=finish+1 end
   if string.sub(out,-1) == "\r" then out=string.sub(out,1,-2) end
   return out
  end
  if type(format) == "number" then
   if self.pos > #self.data then return nil end
   local out=string.sub(self.data,self.pos,self.pos+format-1); self.pos=self.pos+#out; return out
  end
  return nil, "unsupported read format: "..tostring(format)
 end
 function file:lines() return function() return self:read("*l") end end
 function file:seek(whence, offset)
  whence=whence or "cur"; offset=offset or 0
  local base=whence=="set" and 0 or (whence=="end" and #self.data or self.pos-1)
  self.pos=math.max(1,math.min(#self.data+1,base+offset+1)); return self.pos-1
 end
 function file:close() self.closed=true; return true end
 return file
end

-- Load the real, read-only DST foundation tables used by a large share of
-- modmain files. This intentionally stops on upstream drift instead of
-- replacing hundreds of TUNING/constants with fabricated values.
cap("foundation.require", "constants")
require("constants")
cap("foundation.require", "tuning")
require("tuning")
cap("foundation.require", "strings")
require("strings")
