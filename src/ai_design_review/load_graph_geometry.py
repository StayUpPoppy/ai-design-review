"""Conservative fallback for bare dimensions attached to a load diagram.

Only line topology establishes a height. Labels name stations; force magnitude,
spring rate and model-proposed heights never select a dimension.
"""
from __future__ import annotations

import itertools
import math
import re
import statistics
import unicodedata
from .load_height_dimension import HEIGHT_FIELDS, dimension_with_offsets, read_height_dimension
from .load_height_relations import millimeters

VERSION = "load-graph/v3"


def _rotate(x,y,width,height,turn):
    return [(x,y),(height-y,x),(width-x,height-y),(y,width-x)][turn]


def _frame(page,turn):
    width,height=page['width'],page['height']
    def xy(x,y):return _rotate(x,y,width,height,turn)
    def bounds(box):
        x,y,xx,yy=box
        corners=[xy(a,b) for a,b in [(x,y),(x,yy),(xx,y),(xx,yy)]]
        return [min(p[0] for p in corners),min(p[1] for p in corners),max(p[0] for p in corners),max(p[1] for p in corners)]
    texts=[{**t,'bbox':bounds(t['bbox']),
            '_source_boxes':[bounds(box) for box in t.get('_source_boxes',[t['bbox']])]} for t in page['texts']]
    return {**page,'texts':texts,'line_segments':[[*xy(*l[:2]),*xy(*l[2:])] for l in page.get('line_segments',[])],
            'width':height if turn%2 else width,'height':width if turn%2 else height}


def _box_height(t):return max(3,t['bbox'][3]-t['bbox'][1])
def _cx(t):return (t['bbox'][0]+t['bbox'][2])/2
def _cy(t):return (t['bbox'][1]+t['bbox'][3])/2


def _graph_frames(page, force_marks):
    for turn in range(4):
        frame=_frame(page,turn)
        labels=[(p,t) for t in frame['texts'] for p in force_marks(t['text'])]
        if not labels or len(labels)>12:
            continue
        nominal=statistics.median(_box_height(t) for _,t in labels)
        scales=[nominal]
        if len(labels)==1:
            _,label=labels[0]
            nearby=[t for t in frame['texts'] if read_height_dimension(t['text'])
                    and abs(_cx(t)-_cx(label))<=frame['width']*.38
                    and -nominal<=_cy(t)-_cy(label)<=nominal*10]
            glyphs=[box[3]-box[1] for t in [label,*nearby] for box in t['_source_boxes']
                    if 3<=box[3]-box[1]<=nominal and box[2]-box[0]>=box[3]-box[1]]
            if glyphs:
                local=statistics.median(glyphs)
                scales.extend([local,local*.82,local*.67])
        for scale in dict.fromkeys(round(h,2) for h in scales if h>=3):
            yield turn,frame,labels,scale


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


def _dimensions(texts,lines,vs,h,*,allow_scan_gaps=False):
    minimum_segment=.75 if allow_scan_gaps else 1.3
    end_gap=1.05 if allow_scan_gaps else .8
    guide_gap=.85 if allow_scan_gaps else .25
    result=[]
    for t in texts:
        if not read_height_dimension(t['text']):continue
        # A label must be immediately above its own baseline, with connected spans.
        eligible=[]
        for line in lines:
            x,y,xx,yy=line
            if abs(xx-x)<minimum_segment*h or abs(yy-y)>abs(xx-x)*.16:continue
            a=(yy-y)/(xx-x);b=y-a*x;cross=a*_cx(t)+b
            if not -.4*h<cross-t['bbox'][3]<1.25*h:continue
            eligible.append((line,a,b))
        rows=[]
        for seed,a,b in eligible:
            peers=[l for l,aa,bb in eligible if abs((aa-a)*_cx(t)+bb-b)<h*.45
                   and (not allow_scan_gaps or max(abs(l[i+1]-a*l[i]-b) for i in (0,2))<h*.65)]
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
            ends=[]
            for edge in (lo,hi):
                choices=[]
                for i,v in enumerate(vs):
                    p=_intersection(v,a,b)
                    if p and abs(p[0]-edge)<h*end_gap and v['lo']-h*guide_gap<=p[1]<=v['hi']+h*guide_gap:
                        choices.append((abs(p[0]-edge),i,p))
                choices.sort()
                if not choices:break
                if len(choices)>1 and choices[1][0]-choices[0][0]<h*.15:
                    if not allow_scan_gaps or abs(choices[1][2][0]-choices[0][2][0])>h*.4:
                        break
                ends.append(choices[0])
            if len(ends)==2 and ends[0][1]!=ends[1][1]:
                dimension,evidence=dimension_with_offsets(t,texts,a*_cx(t)+b)
                value=millimeters(dimension['value'],dimension['unit'])
                if value is None:continue
                rows.append({'value':value,'text':evidence,'left':ends[0][1],'right':ends[1][1],
                             'a':a,'b':b,'line':seed,'ends':[ends[0][2],ends[1][2]],'reference':dimension['reference_only'],
                             'height_fields':{key:dimension[key] for key in HEIGHT_FIELDS if key in dimension}})
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


def _line_path(lines, start, end, h, *, sloping):
    """Verify printed ink across a span, allowing short scan breaks."""
    distance = end[0]-start[0]
    if abs(distance)<h:
        return False
    slope=(end[1]-start[1])/distance
    intervals=[]
    for x,y,xx,yy in lines:
        if abs(xx-x)<h*.35:
            continue
        line_slope=(yy-y)/(xx-x)
        if sloping and line_slope*slope<=0 or abs(line_slope-slope)>(.30 if sloping else .12):
            continue
        if max(abs(y-start[1]-slope*(x-start[0])),abs(yy-start[1]-slope*(xx-start[0])))>h*(.65 if sloping else .28):
            continue
        lo,hi=sorted(((x-start[0])/distance,(xx-start[0])/distance))
        if hi>=0 and lo<=1:
            intervals.append((lo,hi))
    covered=0
    for lo,hi in sorted(intervals):
        if lo>covered+h*.95/abs(distance):
            break
        covered=max(covered,hi)
    return covered>=1-h*.8/abs(distance)


def _single_station(station, work, contact, dimensions, vs, lines, h):
    """Verify the zero-load end against the full dimension and the graph baseline."""
    peak, curve = contact
    x,y,xx,yy = curve
    zero_side=int((xx>x)==(yy>y))
    conversions=[]
    for full in dimensions:
        if full['value'] <= work['value'] or station in (full['left'],full['right']):
            continue
        xlo,xhi = (p[0] for p in full['ends'])
        if not xlo+h*.5 < peak[0] < xhi-h*.5:
            continue
        zero = full['ends'][zero_side][0]
        fixed = full['ends'][1-zero_side][0]
        work_end=work['ends'][int(work['left']==station)][0]
        absolute=abs(work_end-fixed)<h
        displacement=abs(work_end-zero)<h
        if not absolute and not displacement:
            continue
        for line in lines:
            a,b,c,d = line
            if abs(c-a)<h*.7 or abs(d-b)>abs(c-a)*.16:
                continue
            slope=(d-b)/(c-a)
            offset=b-slope*a
            if min(abs(zero-a),abs(zero-c))>h:
                continue
            base=slope*peak[0]+offset
            end=(zero,slope*zero+offset)
            if not peak[1]+h*.65<base<min(p[1] for p in work['ends'])+h*.2:
                continue
            endpoints=[v['a']*end[1]+v['c'] for v in vs if v['lo']-h*.7<=end[1]<=v['hi']+h*.7
                       and abs(v['a']*end[1]+v['c']-zero)<h*.75]
            if not endpoints:
                continue
            end_x=min(endpoints,key=lambda x:abs(x-zero))
            end=(end_x,slope*end_x+offset)
            if not _line_path(lines,(peak[0],base),end,h,sloping=False) or not _line_path(lines,peak,end,h,sloping=True):
                continue
            if absolute:
                return work
            # Displacement tolerance is not a printed working-height tolerance.
            drawing_ratio=abs(peak[0]-end_x)/abs(xhi-xlo)
            if abs(work['value']/full['value']-drawing_ratio)>.18:
                continue
            conversions.append({**work,'value':round(full['value']-work['value'],12),'distance':work['value'],'height_fields':{},
                                'free_dimension':{'value':full['value'],'text':full['text']}})
            break
    return conversions[0] if len({r['value'] for r in conversions})==1 else None


def _choose_dimension(entries):
    """Same nominal size may be read with and without its smaller offset glyphs."""
    def deviations(dimension):
        return {key:dimension['height_fields'][key] for key in HEIGHT_FIELDS[1:] if key in dimension['height_fields']}

    stated=[entry for entry in entries if deviations(entry[0])]
    dimension,contact=(stated or entries)[0]
    names={item['height_fields']['height_label'] for item,_ in entries if item['height_fields'].get('height_label')}
    if len(names)==1 and not dimension['height_fields'].get('height_label'):
        dimension={**dimension,'height_fields':{**dimension['height_fields'],'height_label':next(iter(names))}}
    if len({tuple(deviations(item).items()) for item,_ in stated})>1:
        height_fields={k:v for k,v in dimension['height_fields'].items() if k=="height_label"}
        height_fields["height_tolerance_status"]="uncertain"
        dimension={**dimension,"height_fields":height_fields}
    return dimension,contact


def geometry_relations(page,*,region=None,diagnostics=None):
    """Return label/force identities with independently grounded absolute heights."""
    from .load_point_evidence import _load_texts,_inside,_text_overlap,force_marks
    texts=_load_texts([t for t in page['texts'] if _inside(t,page,region)])
    if any(re.search(r'(?:单位|units?|dimensions?\s+in)\s*[:：]?\s*(?:inch(?:es)?|cm|英寸|厘米)(?![A-Za-z])',t['text'],re.I) for t in texts):
        return []  # Bare non-mm dimensions need an explicit unit association.
    # Suppress contained partial digit reads; overlapping inconsistent full reads
    # require a unique repeated OCR consensus, otherwise stay unverified.
    numeric=[t for t in texts if re.fullmatch(r'\d+(?:\.\d+)?',unicodedata.normalize('NFKC',t['text']).strip())]
    fragments={id(t) for t in numeric if any(t['text'] in v['text'] and len(t['text'])<len(v['text'])
                                             and _text_overlap(t,v)>.7 for v in numeric)}
    complete=[t for t in numeric if id(t) not in fragments]
    filtered=[]
    for t in texts:
        if id(t) in fragments:continue
        if t in numeric:
            peers=[v for v in complete if v is not t and _text_overlap(t,v)>.7]
            if any(len(v.get('_source_boxes',[]))>=len(t.get('_source_boxes',[])) for v in peers if v['text']!=t['text']):continue
        filtered.append(t)
    original={**page,'texts':filtered}
    if region:
        x,y=region['x']*page['width'],region['y']*page['height'];xx=x+region['width']*page['width'];yy=y+region['height']*page['height']
        original['line_segments']=[l for l in page.get('line_segments',[]) if all(x<=a<=xx and y<=b<=yy for a,b in (l[:2],l[2:]))]
    answers=[]
    def pending(point,text,reason,*,anchor=None):
        if diagnostics is not None:
            diagnostics.append({'label':point['label'],'force':point['force'],'force_unit':point['force_unit'],'reason':reason,
                                'force_bbox':original['texts'][texts.index(text)]['bbox'],'force_verified':anchor is not None,'graph_order':anchor})
    for turn,framed,labels,h in _graph_frames(original,force_marks):
        texts=framed['texts'];lines=framed['line_segments']
        vs=_verticals(lines,h);dimensions=_dimensions(texts,lines,vs,h,allow_scan_gaps=len(labels)==1)
        for datum in range(len(vs)):
            group=[r for r in dimensions if datum in (r['left'],r['right'])]
            if not group:continue
            stations={}
            for r in group:
                station=r['right'] if r['left']==datum else r['left'];v=vs[station]
                if v['lo']>=min(p[1] for p in r['ends'])-h:continue
                contact=_curve_contact(v,lines,h)
                if contact:
                    stations.setdefault(station,[]).append((r,contact))
            if len(labels)==1:
                stations={station:[(verified,contact) for r,contact in entries
                                   if (verified:=_single_station(station,r,contact,dimensions,vs,lines,h))]
                          for station,entries in stations.items()}
                stations={station:entries for station,entries in stations.items() if entries}
            elif len(stations)==1:
                station,entries=next(iter(stations.items()))
                stations={station:[(verified,contact) for r,contact in entries
                                   if (verified:=_single_station(station,r,contact,dimensions,vs,lines,h))]}
                if not stations[station]:continue
            if not stations:continue
            choices=[]
            for point,t in labels:
                possible=[]
                leaders=_leader_hits(t,stations,lines,vs,h)
                if len(leaders)>1:
                    pending(point,t,'载荷引出线存在多个合理落点，请核对原图')
                    continue
                for station,entries in stations.items():
                    values={r['value'] for r,_ in entries}
                    r,contact=_choose_dimension(entries);p,curve=contact
                    distance=_distance_box(p,t)
                    if leaders and station not in leaders:continue
                    if not leaders and (distance>h*.85 or p[1]<t['bbox'][1]-h*.2):continue
                    # The station is directly adjacent to the label and above its dimension.
                    if _cy(t)>=min(q[1] for q in r['ends']):continue
                    if len(values)!=1:
                        pending(point,t,'同一载荷落点有多个高度读数，请核对原图',anchor=p)
                        continue
                    possible.append((-h if leaders else distance,station,r,contact,leaders.get(station,[])))
                choices.append((point,t,possible))
                if not possible:
                    pending(point,t,'载荷标注与尺寸界线未形成唯一关联，请核对原图')
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
                for point,t,possible in available:
                    pending(point,t,'存在多个合理的载荷高度对应关系，请核对原图',anchor=possible[0][3][0])
                continue
            for (point,t,_),(_,station,r,contact,leader) in zip(available,solutions[0][1]):
                def inverse(p):
                    return _rotate(*p,framed['width'],framed['height'],(-turn)%4)
                def normalized(p):
                    x,y=inverse(p);return {'x':x/page['width'],'y':y/page['height']}
                def original_box(box):
                    x,y,xx,yy=box
                    corners=[inverse(p) for p in [(x,y),(x,yy),(xx,y),(xx,yy)]]
                    xs,ys=zip(*corners)
                    return [min(xs),min(ys),max(xs),max(ys)]
                answers.append({'label':point['label'],'force':point['force'],'force_unit':point['force_unit'],
                    'value':r['value'],'reference_only':r['reference'],'verification_method':'dimension_leader' if leader else 'dimension_graph',
                    'geometry_evidence':{'version':VERSION,'datum':normalized(r['ends'][0 if r['left']==datum else 1]),
                        'dimension_endpoints':[normalized(p) for p in r['ends']],
                        'load_anchor':normalized(contact[0]),'curve_segment':[normalized(contact[1][:2]),normalized(contact[1][2:])],
                        'leader_path':[[normalized(l[:2]),normalized(l[2:])] for l in leader]},
                    'dimension_text':r['text']['text'],'dimension_bbox':original_box(r['text']['bbox']),
                    'force_bbox':original['texts'][texts.index(t)]['bbox'],'graph_order':contact[0],
                    'distance':r.get('distance',r['value']),
                    'free_dimension':{'value':r['free_dimension']['value'],
                                      'text':{'text':r['free_dimension']['text']['text'],
                                              'bbox':original_box(r['free_dimension']['text']['bbox'])}} if r.get('free_dimension') else None,
                    'height_fields':r['height_fields']})
    grouped={}
    for answer in answers:grouped.setdefault((tuple(answer['force_bbox']),answer['label'].casefold(),answer['force'],answer['force_unit']),[]).append(answer)
    resolved=[]
    for rows in grouped.values():
        if len({r['value'] for r in rows})==1:
            chosen,_=_choose_dimension([(r,None) for r in rows])
            resolved.append(chosen)
        elif diagnostics is not None:
            first=rows[0]
            diagnostics.append({**{key:first[key] for key in ('label','force','force_unit','force_bbox','graph_order')},
                                'force_verified':True,'reason':'同一载荷有多个可读高度，请核对原图'})
    return resolved
