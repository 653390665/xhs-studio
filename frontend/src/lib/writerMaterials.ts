export interface WriterMaterial {id:string;kind:string|null;title:string;body:string;batch:string}
interface SavedDraft { at?:number; id?:number; kind?:string|null; title?:string; body?:string; batch?:string; batchName?:string }
function parse<T>(storage:Storage,key:string,fallback:T):T{try{const raw=storage.getItem(key);return raw?JSON.parse(raw) as T:fallback;}catch{return fallback;}}
export function writerMaterialBatches():Array<{id:string;name:string}>{
 const names=new Map<string,string>();
 for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(key?.startsWith('xhs.studio.results.')){const id=key.slice('xhs.studio.results.'.length);if(id)names.set(id,id);}}
 for(const item of parse<SavedDraft[]>(localStorage,'xhs.studio.drafts',[])){if(item.batch)names.set(item.batch,item.batchName||item.batch);}
 for(let i=0;i<sessionStorage.length;i++){const key=sessionStorage.key(i);if(key?.startsWith('xhs.studio.')&&!key.startsWith('xhs.studio.drafts')&&!key.startsWith('xhs.studio.results.')){const id=key.slice('xhs.studio.'.length);if(id)names.set(id,names.get(id)||id);}}
 return [...names].map(([id,name])=>({id,name}));
}
export function writerMaterialSnapshot(batchId:string):WriterMaterial[]{
 const items:WriterMaterial[]=[];
 const results=parse<Record<string,{md?:string;title?:string}>>(localStorage,'xhs.studio.results.'+batchId,{});
 for(const [kind,value] of Object.entries(results)){if(value&&typeof value.md==='string'&&value.md)items.push({id:'result:'+kind,kind,title:value.title||kind,body:value.md,batch:batchId});}
 for(const draft of parse<SavedDraft[]>(localStorage,'xhs.studio.drafts',[])){if(draft.batch===batchId&&typeof draft.body==='string')items.push({id:'draft:'+String(draft.id??draft.at),kind:draft.kind??null,title:draft.title||'未命名草稿',body:draft.body,batch:batchId});}
 /*
  * 提炼工作台里新建/手写的模板，不属于当前这一批也要进索引。
  * 人刚在那边存了一份「反常识开头」，回到写稿页却看不见、还得重新挑批次同步一次，
  * 那份模板就等于白存了。这里按最近 30 条挂进每一批，id 以 lib: 开头以便区分出处。
  */
 const library=parse<SavedDraft[]>(localStorage,'xhs.studio.drafts',[])
  .filter(draft=>typeof draft.body==='string'&&draft.body.length>0&&draft.batch!==batchId)
  .sort((a,b)=>(b.at??0)-(a.at??0)).slice(0,30);
 for(const draft of library)items.push({id:'lib:'+String(draft.at??draft.id),kind:draft.kind??null,title:draft.title||'未命名模板',body:draft.body as string,batch:batchId});
 const hasCanonicalResults=localStorage.getItem('xhs.studio.results.'+batchId)!==null;
 const session=parse<{md?:string;resultKind?:string;title?:string;results?:Record<string,{md?:string;title?:string}>}>(sessionStorage,'xhs.studio.'+batchId,{});
 for(const [kind,value] of Object.entries(hasCanonicalResults?{}:session.results||{})){if(!results[kind]?.md&&typeof value?.md==='string'&&value.md)items.push({id:'session-result:'+kind,kind,title:value.title||kind,body:value.md,batch:batchId});}
 if(!hasCanonicalResults&&session.md&&session.resultKind&&!items.some(item=>item.body===session.md&&item.kind===session.resultKind))items.push({id:'session-current:'+session.resultKind,kind:session.resultKind,title:session.title||'当前未另存结果',body:session.md,batch:batchId});
 return items.sort((a,b)=>a.id.localeCompare(b.id));
}

const revisionKey=(batch:string)=>'xhs.writer.material-revision.'+batch;
const LIBRARY_REVISION='xhs.writer.material-revision.__library';
export function writerMaterialRevision(batch:string):number{
 /* 模板库变了这一批的素材也就变了，所以取两者较大的那个，否则同步会一直撞版本冲突 */
 const batchValue=Number(localStorage.getItem(revisionKey(batch)));
 const libraryValue=Number(localStorage.getItem(LIBRARY_REVISION));
 const value=Math.max(Number.isSafeInteger(batchValue)&&batchValue>=0?batchValue:0,Number.isSafeInteger(libraryValue)&&libraryValue>=0?libraryValue:0);
 return value;
}
export function notifyWriterMaterialSave(batches:string[]):void{
 for(const batch of new Set(batches.filter(Boolean))){try{localStorage.setItem(revisionKey(batch),String(Math.max(Date.now(),writerMaterialRevision(batch)+1)));}catch{/* A failed revision write is reported as a safe sync conflict, not overwritten. */}}
 try{localStorage.setItem(LIBRARY_REVISION,String(Date.now()));}catch{/* 同上：读不到就按冲突处理，不静默覆盖 */}
 window.dispatchEvent(new Event('xhs:studio-materials-changed'));
}
export function writerSessionMaterialSignature(raw:string|null):string{try{const value=JSON.parse(raw||'{}');return JSON.stringify({md:value.md||'',kind:value.resultKind||'',results:value.results||{}});}catch{return '{}';}}
