/* Session-only saved snapshots and bounded decoded preview images. */
(function(root){
  function create({limit=3,pixelBudget=128*1024*1024,onEvict=()=>{}}={}){
    const entries=new Map();let scope=null;
    function remove(id){const item=entries.get(id);if(!item)return;entries.delete(id);if(item.image){item.image.onload=null;item.image.onerror=null;item.image.src='';item.image=null;}onEvict(id);}
    function bytes(){return [...entries.values()].reduce((n,v)=>n+(v.image?v.image.naturalWidth*v.image.naturalHeight*4:0),0);}
    function trim(){while(entries.size>limit)remove(entries.keys().next().value);for(const [id,item] of entries){if(bytes()<=pixelBudget)break;if(item.image){item.image.onload=null;item.image.src='';item.image=null;}}}
    function reset(next){if(scope===next)return;for(const id of [...entries.keys()])remove(id);scope=next;}
    function get(id){const item=entries.get(id);if(item){entries.delete(id);entries.set(id,item);}return item;}
    function put(id,value){const previous=entries.get(id);if(previous?.image){previous.image.onload=null;previous.image.src='';}entries.delete(id);const item={...value,review:structuredClone(value.review),image:null};entries.set(id,item);trim();return item;}
    function preload(id,url){const item=entries.get(id);if(!item||!url||typeof Image==='undefined')return;const image=new Image();item.image=image;image.onload=()=>{if(entries.get(id)===item)trim();};image.src=url;trim();}
    return {reset,get,put,remove,preload,stats:()=>({entries:entries.size,pixelBytes:bytes()}),ids:()=>[...entries.keys()]};
  }
  root.ReviewSwitchCache={create};
})(globalThis);
