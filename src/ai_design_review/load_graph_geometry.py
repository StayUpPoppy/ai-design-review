"""Conservative fallback for bare dimensions attached to a load diagram.

Only line topology establishes a height. Labels name stations; force magnitude,
spring rate and model-proposed heights never select a dimension.
"""
from __future__ import annotations

from copy import deepcopy
import itertools
import math
import re
import statistics
import unicodedata

VERSION = "load-graph/v1"


def _rotate(x,y,width,height,turn):
    return [(x,y),(height-y,x),(width-x,height-y),(y,width-x)][turn]


def _frame(page,turn):
    width,height=page['width'],page['height']
    def xy(x,y):return _rotate(x,y,width,height,turn)
    texts=[]
    for t in page['texts']:
        x,y,xx,yy=t['bbox'];corners=[xy(a,b) for a,b in [(x,y),(x,yy),(xx,y),(xx,yy)]]
        texts.append({**t,'bbox':[min(p[0] for p in corners),min(p[1] for p in corners),max(p[0] for p in corners),max(p[1] for p in corners)]})
    return {**page,'texts':texts,'line_segments':[[*xy(*l[:2]),*xy(*l[2:])] for l in page.get('line_segments',[])],
            'width':height if turn%2 else width,'height':width if turn%2 else height}


def _box_height(t):return max(3,t['bbox'][3]-t['bbox'][1])
def _cx(t):return (t['bbox'][0]+t['bbox'][2])/2
def _cy(t):return (t['bbox'][1]+t['bbox'][3])/2


def _verticals(lines,h):
    candidates=[]
    for x,y,xx,yy in lines:
        if abs(yy-y)<.55*h or abs(xx-x)>abs(yy-y)*.15:continue
        if y>yy:x,y,xx,yy=xx,yy,x,y
        a=(xx-x)/(yy-y);c=x-a*y
        candidates.append(dict(a=a,c=c,lo=y,hi=yy,lines=[[x,y,xx,yy]]))
    groups=[]
    for v in sorted(candidates,key=lambda v:v['lo']):
        for g in groups:
            common=max(v['lo'],g['lo']);distance=abs((v['a']-g['a'])*common+v['c']-g['c'])
            if distance<h*.22 and v['lo']<=g['hi']+h*.65 and abs(v['a']-g['a'])<.1:
                g['lo']=min(g['lo'],v['lo']);g['hi']=max(g['hi'],v['hi']);g['lines']+=v['lines'];break
        else:groups.append(v)
    return groups


def _intersection(v,a,b):
    denominator=1-v['a']*a
    if abs(denominator)<.1:return None
    x=(v['a']*b+v['c'])/denominator
    return (x,a*x+b)


def _dimensions(texts,lines,vs,h):
    result=[]
    for t in texts:
        match=re.fullmatch(r'\s*([（(]?)(\d+(?:\.\d+)?)[）)]?\s*(?:mm|毫米)?\s*',unicodedata.normalize('NFKC',t['text']),re.I)
        if not match or float(match[2])<=0:continue
        # A label must be immediately above its own baseline, with connected spans.
        eligible=[]
        for line in lines:
            x,y,xx,yy=line
            if abs(xx-x)<1.3*h or abs(yy-y)>abs(xx-x)*.16:continue
            a=(yy-y)/(xx-x);b=y-a*x;cross=a*_cx(t)+b
            if not -.4*h<cross-t['bbox'][3]<1.25*h:continue
            eligible.append((line,a,b))
        rows=[]
        for seed,a,b in eligible:
            peers=[l for l,aa,bb in eligible if abs((aa-a)*_cx(t)+bb-b)<h*.45]
            components=[]
            for l in sorted(peers,key=lambda l:min(l[0],l[2])):
                lo,hi=min(l[0],l[2]),max(l[0],l[2])
                if components and lo<=components[-1][1]+h*1.5:
                    components[-1][1]=max(hi,components[-1][1]);components[-1][2].append(l)
                else:components.append([lo,hi,[l]])
            component=next((c for c in components if c[0]<=_cx(t)<=c[1]),None)
            if not component:continue
            lo,hi,peers=component
            if not lo<=_cx(t)<=hi or hi-lo<3*h:continue
            # Join segments only across small gaps; do not bridge another table cell.
            spans=sorted((min(l[0],l[2]),max(l[0],l[2])) for l in peers)
            if any(right[0]-left[1]>h*1.5 for left,right in zip(spans,spans[1:])):continue
            ends=[]
            for edge in (lo,hi):
                choices=[]
                for i,v in enumerate(vs):
                    p=_intersection(v,a,b)
                    if p and abs(p[0]-edge)<h*.8 and v['lo']-h*.25<=p[1]<=v['hi']+h*.25:
                        choices.append((abs(p[0]-edge),i,p))
                choices.sort()
                if not choices:break
                if len(choices)>1 and choices[1][0]-choices[0][0]<h*.15:break
                ends.append(choices[0])
            if len(ends)==2 and ends[0][1]!=ends[1][1]:
                rows.append({'value':float(match[2]),'text':t,'left':ends[0][1],'right':ends[1][1],
                             'a':a,'b':b,'line':seed,'ends':[ends[0][2],ends[1][2]],'reference':bool(match[1])})
        if rows:
            rows.sort(key=lambda r:abs(r['a']*_cx(t)+r['b']-t['bbox'][3]))
            result.append(rows[0])
    return result


def _curve_contact(v,lines,h):
    contacts=[]
    obliques=[]
    for line in lines:
        x,y,xx,yy=line
        if abs(xx-x)<h*.4 or not .2<abs((yy-y)/(xx-x))<2:continue
        obliques.append(line)
    for line in obliques:
        x,y,xx,yy=line
        a=(yy-y)/(xx-x);b=y-a*x;p=_intersection(v,a,b)
        if not p:continue
        lo,hi=sorted((x,xx))
        supported=lo-h*.25<=p[0]<=hi+h*.25
        if not supported and lo-h*1.2<=p[0]<=hi+h*1.2:
            # Interpolate a short break only when a collinear segment exists
            # on the other side; never extend a lone line toward a guessed point.
            for other in obliques:
                u,w,uu,ww=other;aa=(ww-w)/(uu-u);bb=w-aa*u
                low,high=sorted((u,uu))
                opposite=hi<p[0]<low or high<p[0]<lo
                if opposite and min(abs(p[0]-low),abs(p[0]-high))<h*1.2 and abs((aa-a)*p[0]+bb-b)<h*.2:
                    supported=True;break
        if supported and abs(p[1]-v['lo'])<h*.6:
            contacts.append((p,line))
    if not contacts:return None
    return min(contacts,key=lambda p:abs(p[0][1]-v['lo']))


def _distance_box(point,t):
    x,y=point;a,b,c,d=t['bbox']
    return math.hypot(max(a-x,0,x-c),max(b-y,0,y-d))


def _leader_hits(text,stations,lines,vs,h):
    """Trace short connected leader polylines, stopping at the first graph anchor.

    The load curve and station guides cannot themselves be a label's leader.
    Crossing segments are not connected unless their endpoints meet.
    """
    anchors={i:entries[0][1][0] for i,entries in stations.items()}
    ceiling=min(min(p[1] for p in entries[0][0]['ends']) for entries in stations.values())
    candidates=[]
    for line in lines:
        x,y,xx,yy=line;length=math.hypot(xx-x,yy-y)
        if length<h*.5 or max(y,yy)>ceiling-h*.2:continue
        if abs(xx-x)<abs(yy-y)*.15 and any(abs(x-(v['a']*y+v['c']))<h*.25 for i,v in enumerate(vs) if i in stations):continue
        on_curve=False
        if abs(xx-x)>h*.3:
            a=(yy-y)/(xx-x);b=y-a*x
            for entries in stations.values():
                anchor,curve=entries[0][1];u,w,uu,ww=curve
                ca=(ww-w)/(uu-u)
                if abs(a-ca)<.15 and abs(a*anchor[0]+b-anchor[1])<h*.25:
                    on_curve=True;break
        if not on_curve:candidates.append(line)
    hits={};queue=[]
    for i,line in enumerate(candidates):
        for a,b in [(line[:2],line[2:]),(line[2:],line[:2])]:
            if _distance_box(a,text)<=h*.25 and _distance_box(b,text)>h*.2:
                queue.append((b,[line],{i}))
    while queue:
        node,path,seen=queue.pop()
        hit=[i for i,p in anchors.items() if math.dist(node,p)<h*.35]
        if hit:
            for i in hit:hits.setdefault(i,path)
            continue
        if len(path)>=4:continue
        for i,line in enumerate(candidates):
            if i in seen:continue
            for a,b in [(line[:2],line[2:]),(line[2:],line[:2])]:
                if math.dist(a,node)<h*.25 and sum(math.dist(l[:2],l[2:]) for l in [*path,line])<h*12:
                    queue.append((b,[*path,line],seen|{i}))
    return hits


def geometry_relations(page,*,region=None,diagnostics=None):
    """Return label/force identities with independently grounded absolute heights."""
    from .load_point_evidence import _deduplicate_texts,_inside,extract_force_annotations
    texts=_deduplicate_texts([t for t in page['texts'] if _inside(t,page,region)])
    if any(re.search(r'(?:单位|units?|dimensions?\s+in)\s*[:：]?\s*(?:inch(?:es)?|cm|英寸|厘米)(?![A-Za-z])',t['text'],re.I) for t in texts):
        return []  # Bare non-mm dimensions need an explicit unit association.
    # Suppress contained partial digit reads; overlapping inconsistent full reads
    # require a unique repeated OCR consensus, otherwise stay unverified.
    numeric=[t for t in texts if re.fullmatch(r'\d+(?:\.\d+)?',unicodedata.normalize('NFKC',t['text']).strip())]
    def overlap(a,b):
        x,y,xx,yy=a['bbox'];u,v,uu,vv=b['bbox']
        return max(0,min(xx,uu)-max(x,u))*max(0,min(yy,vv)-max(y,v))/max(1,min((xx-x)*(yy-y),(uu-u)*(vv-v)))
    filtered=[]
    for t in texts:
        if t in numeric:
            peers=[v for v in numeric if v is not t and overlap(t,v)>.7]
            if any(t['text'] in v['text'] and len(t['text'])<len(v['text']) for v in peers):continue
            if any(len(v.get('_source_boxes',[]))>=len(t.get('_source_boxes',[])) for v in peers if v['text']!=t['text']):continue
        filtered.append(t)
    original={**page,'texts':filtered}
    if region:
        x,y=region['x']*page['width'],region['y']*page['height'];xx=x+region['width']*page['width'];yy=y+region['height']*page['height']
        original['line_segments']=[l for l in page.get('line_segments',[]) if all(x<=a<=xx and y<=b<=yy for a,b in (l[:2],l[2:]))]
    answers=[]
    def pending(point,reason):
        if diagnostics is not None:
            diagnostics.append({'label':point['label'],'force':point['force'],'force_unit':point['force_unit'],'reason':reason})
    for turn in range(4):
        framed=_frame(original,turn);texts=framed['texts'];lines=framed['line_segments']
        labels=[]
        for t in texts:
            for p in extract_force_annotations(t['text']):
                if re.match(r'^'+re.escape(p['label'])+r'[=:：＝]',re.sub(r'\s+','',unicodedata.normalize('NFKC',t['text'])),re.I):labels.append((p,t))
        if not labels or len(labels)>12:continue
        h=statistics.median(_box_height(t) for _,t in labels)
        vs=_verticals(lines,h);dimensions=_dimensions(texts,lines,vs,h)
        for datum in range(len(vs)):
            group=[r for r in dimensions if datum in (r['left'],r['right'])]
            if len({r['value'] for r in group})<2:continue
            stations={}
            for r in group:
                station=r['right'] if r['left']==datum else r['left'];v=vs[station]
                if v['lo']>=min(p[1] for p in r['ends'])-h:continue
                contact=_curve_contact(v,lines,h)
                if contact:
                    stations.setdefault(station,[]).append((r,contact))
            # At least two stations on a genuine sloping load diagram, not a lone dimension.
            if len(stations)<2:continue
            choices=[]
            for point,t in labels:
                possible=[]
                leaders=_leader_hits(t,stations,lines,vs,h)
                if len(leaders)>1:
                    pending(point,'载荷引出线存在多个合理落点，请核对原图')
                    continue
                for station,entries in stations.items():
                    values={r['value'] for r,_ in entries}
                    if len(values)!=1:continue
                    r,contact=entries[0];p,curve=contact
                    distance=_distance_box(p,t)
                    if leaders and station not in leaders:continue
                    if not leaders and (distance>h*.85 or p[1]<t['bbox'][1]-h*.2):continue
                    # The station is directly adjacent to the label and above its dimension.
                    if _cy(t)>=min(q[1] for q in r['ends']):continue
                    possible.append((-h if leaders else distance,station,r,contact,leaders.get(station,[])))
                choices.append((point,t,possible))
                if not possible:
                    pending(point,'载荷标注与尺寸界线未形成唯一关联，请核对原图')
            available=[c for c in choices if c[2]]
            if not available:continue
            combinations=math.prod(len(c[2]) for c in available)
            if combinations>20000:continue
            solutions=[]
            for assignment in itertools.product(*(c[2] for c in available)):
                if len({a[1] for a in assignment})!=len(assignment):continue
                solutions.append((sum(a[0] for a in assignment),assignment))
            solutions.sort(key=lambda s:s[0])
            if not solutions or len(solutions)>1 and solutions[1][0]-solutions[0][0]<h*.25:
                for point,_,_ in available:
                    pending(point,'存在多个合理的载荷高度对应关系，请核对原图')
                continue
            for (point,t,_),(_,station,r,contact,leader) in zip(available,solutions[0][1]):
                def inverse(p):
                    return _rotate(*p,framed['width'],framed['height'],(-turn)%4)
                def normalized(p):
                    x,y=inverse(p);return {'x':x/page['width'],'y':y/page['height']}
                answers.append({'label':point['label'],'force':point['force'],'force_unit':point['force_unit'],
                    'value':r['value'],'reference_only':r['reference'],'verification_method':'dimension_leader' if leader else 'dimension_graph',
                    'geometry_evidence':{'version':VERSION,'datum':normalized(r['ends'][0 if r['left']==datum else 1]),
                        'dimension_endpoints':[normalized(p) for p in r['ends']],
                        'load_anchor':normalized(contact[0]),'curve_segment':[normalized(contact[1][:2]),normalized(contact[1][2:])],
                        'leader_path':[[normalized(l[:2]),normalized(l[2:])] for l in leader]},
                    'dimension_text':r['text']['text'],'dimension_bbox':deepcopy(original['texts'][texts.index(r['text'])]['bbox'])})
    grouped={}
    for answer in answers:grouped.setdefault((answer['label'].casefold(),answer['force'],answer['force_unit']),[]).append(answer)
    return [rows[0] for rows in grouped.values() if len({r['value'] for r in rows})==1]
