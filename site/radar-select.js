/* Shared single-select UI. Native controls remain the source of form values. */
(function(host){
  'use strict';
  if(host.RadarSelect)return;
  const doc=host.document,instances=new WeakMap(),live=new Set();let active=null,serial=0;
  const node=(tag,cls,text)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
  function entries(select){return Array.from(select.options).map((option,index)=>({index,value:option.value,text:option.textContent.trim(),group:option.parentElement?.tagName==='OPTGROUP'?option.parentElement.label:'',disabled:option.disabled||option.parentElement?.disabled,selected:option.selected,hidden:option.hidden||option.parentElement?.hidden})).filter(option=>!option.hidden);}
  function controlLabel(select){
    const explicit=select.getAttribute('aria-label');if(explicit)return explicit;
    const label=select.labels?.[0];
    const text=label&&Array.from(label.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
    return text||select.title||'选择选项';
  }
  function enhance(select){
    if(instances.has(select))return instances.get(select);
    if(select.multiple||select.size>1||['pair-left','pair-right'].includes(select.id)||select.classList.contains('pair-native-select'))return null;
    const id='radar-select-'+(++serial),root=node('span','radar-select'),button=node('button','radar-select-control'),caption=node('span','radar-select-caption'),caret=node('span','radar-select-caret');
    const panel=node('div','radar-select-panel'),heading=node('div','radar-select-heading'),title=node('strong'),closeButton=node('button','radar-select-close','×'),search=node('input','radar-select-search'),list=node('div','radar-select-list'),footer=node('div','radar-select-footer');
    button.type=closeButton.type='button';button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls',id);caret.setAttribute('aria-hidden','true');button.append(caption,caret);root.append(button);select.after(root);select.classList.add('radar-native-select');
    panel.id=id;panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label',controlLabel(select));
    closeButton.setAttribute('aria-label','关闭选项');heading.append(title,closeButton);
    search.type='search';search.placeholder='搜索选项…';search.autocomplete='off';search.setAttribute('role','combobox');search.setAttribute('aria-autocomplete','list');search.setAttribute('aria-expanded','false');search.setAttribute('aria-controls',id+'-list');
    list.id=id+'-list';list.tabIndex=0;list.setAttribute('role','listbox');panel.append(heading,search,list,footer);(select.closest('dialog')||doc.body).append(panel);
    const topLayer=typeof panel.showPopover==='function';if(topLayer)panel.setAttribute('popover','manual');
    let opened=false,items=[],buttons=[],highlighted=-1,limit=80;const patchedProperties=[];
    const focusOwner=()=>search.hidden?list:search;
    function sync(){
      const selected=select.selectedOptions[0],label=controlLabel(select),text=selected?.textContent.trim()||'暂无选项';
      if(caption.textContent!==text)caption.textContent=text;
      button.title=select.title?text+' · '+select.title:text;button.disabled=select.disabled||!select.options.length;button.setAttribute('aria-label',label+'：'+text);button.setAttribute('aria-required',String(select.required));
      root.hidden=select.hidden||select.style.display==='none';root.style.width=select.style.width||'';root.style.maxWidth=select.style.maxWidth||'';
      title.textContent=label;panel.setAttribute('aria-label',label);list.setAttribute('aria-label',label);search.setAttribute('aria-label','搜索'+label);
      if(opened&&(root.hidden||button.disabled||!root.isConnected))close();
      else if(opened)render();
    }
    function close(restore=false){
      if(!opened)return;opened=false;if(active===api)active=null;
      if(topLayer){try{panel.hidePopover();}catch{}}
      panel.hidden=true;button.setAttribute('aria-expanded','false');search.setAttribute('aria-expanded','false');list.removeAttribute('aria-activedescendant');search.removeAttribute('aria-activedescendant');
      if(restore&&button.isConnected)button.focus({preventScroll:true});
    }
    function highlight(index,scroll=false){
      highlighted=index;buttons.forEach((b,i)=>b.classList.toggle('is-active',i===index));
      if(buttons[index]){focusOwner().setAttribute('aria-activedescendant',buttons[index].id);if(scroll)buttons[index].scrollIntoView({block:'nearest'});}
    }
    function render(){
      const all=entries(select),query=search.value.trim().toLocaleLowerCase();items=all.filter(o=>(o.text+' '+o.group).toLocaleLowerCase().includes(query));
      list.replaceChildren();buttons=[];highlighted=-1;search.removeAttribute('aria-activedescendant');list.removeAttribute('aria-activedescendant');let previousGroup='';
      for(const item of items.slice(0,limit)){
        if(item.group&&item.group!==previousGroup)list.append(node('div','radar-select-group',item.group));previousGroup=item.group;
        const option=node('button','radar-select-option'),text=node('span','radar-select-option-text',item.text),check=node('span','radar-select-check');option.type='button';option.tabIndex=-1;option.id=id+'-option-'+item.index;option.disabled=Boolean(item.disabled);option.setAttribute('role','option');option.setAttribute('aria-selected',String(item.selected));check.setAttribute('aria-hidden','true');option.append(text,check);option.title=item.text;
        option.onclick=()=>{if(item.disabled)return;const changed=select.selectedIndex!==item.index;select.selectedIndex=item.index;close(true);sync();if(changed){select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));}};
        const i=buttons.length;option.onpointermove=()=>highlight(i);buttons.push(option);list.append(option);
      }
      if(!items.length)list.append(node('p','radar-select-empty','没有匹配的选项'));
      footer.replaceChildren(node('span',null,query?`${items.length} 项匹配`:`${all.length} 个选项`));
      if(items.length>limit){const more=node('button','radar-select-more','继续显示');more.type='button';more.onclick=()=>{limit+=80;render();focusOwner().focus({preventScroll:true});place();};footer.append(more);}
    }
    function place(){
      const rect=button.getBoundingClientRect(),view=host.visualViewport,w=view?.width||host.innerWidth,h=view?.height||host.innerHeight,ox=view?.offsetLeft||0,oy=view?.offsetTop||0;
      const below=h-(rect.bottom-oy)-12,above=rect.top-oy-12,down=below>=220||below>=above;
      panel.style.width=Math.min(Math.max(rect.width,260),460,w-24)+'px';panel.style.maxHeight=Math.max(100,Math.min(470,down?below:above))+'px';
      panel.style.left=Math.max(ox+12,Math.min(rect.left,ox+w-12-parseFloat(panel.style.width)))+'px';
      panel.style.top=(down?rect.bottom+7:Math.max(oy+12,rect.top-7-panel.getBoundingClientRect().height))+'px';
    }
    function open(){
      sync();if(button.disabled||root.hidden)return;
      active?.close();doc.dispatchEvent(new Event('radar-pair-picker-open'));
      search.value='';search.hidden=select.options.length<8;limit=80;render();panel.hidden=false;
      if(topLayer)panel.showPopover();opened=true;active=api;button.setAttribute('aria-expanded','true');search.setAttribute('aria-expanded','true');place();focusOwner().focus({preventScroll:true});
      const selected=buttons.findIndex(b=>b.getAttribute('aria-selected')==='true');highlight(selected>=0?selected:buttons.findIndex(b=>!b.disabled),true);
    }
    function next(direction){
      let i=highlighted;for(let n=0;n<buttons.length;n++){i=(i+direction+buttons.length)%buttons.length;if(!buttons[i].disabled){highlight(i,true);return;}}
    }
    button.onclick=()=>opened?close(true):open();closeButton.onclick=()=>close(true);
    button.onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open();if(e.key==='ArrowUp')next(-1);}};
    panel.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}else if(e.target===search||e.target===list){if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();next(e.key==='ArrowDown'?1:-1);}else if(e.key==='Enter'&&buttons[highlighted]){e.preventDefault();buttons[highlighted].click();}else if(e.target===list&&e.key.length===1&&!e.ctrlKey&&!e.metaKey){const i=items.findIndex(o=>o.text.toLocaleLowerCase().startsWith(e.key.toLocaleLowerCase()));if(i>=0)highlight(i,true);}}};
    search.oninput=()=>{limit=80;render();list.scrollTop=0;place();};
    select.addEventListener('change',sync);
    // App-driven .value assignments do not emit events. Keep their caption in
    // sync immediately, without changing native values or dispatching changes.
    for(const property of ['value','selectedIndex']){
      const descriptor=Object.getOwnPropertyDescriptor(host.HTMLSelectElement.prototype,property);
      if(descriptor?.get&&descriptor?.set&&!Object.hasOwn(select,property)){Object.defineProperty(select,property,{configurable:true,get(){return descriptor.get.call(this);},set(v){descriptor.set.call(this,v);sync();}});patchedProperties.push(property);}
    }
    const api={select,root,panel,button,open,close,sync,destroy(){close();panel.remove();root.remove();select.classList.remove('radar-native-select');select.removeEventListener('change',sync);for(const property of patchedProperties)delete select[property];live.delete(api);instances.delete(select);}};
    instances.set(select,api);live.add(api);sync();return api;
  }
  function scan(root=doc){
    if(root.matches?.('select'))enhance(root);
    for(const select of root.querySelectorAll?.('select')||[])enhance(select);
  }
  function start(){
    scan();
    new host.MutationObserver(records=>{
      const dirty=new Set();for(const record of records){const target=record.target.nodeType===1?record.target:record.target.parentElement,select=target?.closest?.('select');if(select&&instances.has(select))dirty.add(instances.get(select));
        for(const added of record.addedNodes||[])if(added.nodeType===1)scan(added);
      }
      for(const api of dirty)api.sync();for(const api of live)if(!api.select.isConnected)api.destroy();
    }).observe(doc.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['disabled','hidden','label','selected','value','style','aria-label']});
    doc.addEventListener('pointerdown',e=>{if(active&&!active.root.contains(e.target)&&!active.panel.contains(e.target))active.close();});
    doc.addEventListener('focusin',e=>{if(active&&!active.root.contains(e.target)&&!active.panel.contains(e.target))active.close();});
    doc.addEventListener('scroll',e=>{if(active&&!active.panel.contains(e.target))active.close();},true);
    doc.addEventListener('radar-pair-picker-open',()=>active?.close());host.addEventListener('resize',()=>active?.close());
    doc.addEventListener('click',e=>{const label=e.target.closest?.('label[for]'),select=label&&doc.getElementById(label.htmlFor),api=select&&instances.get(select);if(api&&!api.root.contains(e.target)){e.preventDefault();api.button.focus({preventScroll:true});}});
  }
  host.RadarSelect={enhance,scan,entries};
  if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',start,{once:true});else start();
})(window);
