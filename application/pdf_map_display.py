"""Read-only PDF vector display; never creates or approves physical tube records."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

@lru_cache(maxsize=64)
def _centers(path, modified_ns, size, page_number, expected_count, expected_hash):
    import pymupdf
    from iris2.pdf_tube_sheet_geometry import extract_tube_centers
    source=Path(path)
    with source.open('rb') as stream:
        digest=sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    if digest.hexdigest().lower()!=expected_hash.lower():return ()
    with pymupdf.open(source) as document:
        if not 1<=page_number<=len(document):return ()
        points=extract_tube_centers(document[page_number-1],expected_count)
    return tuple(points) if len(points)==expected_count else ()

def pdf_vector_display(path,page_number,expected_count,expected_hash,tubes):
    """Return None on uncertain numbering/count/hash rather than remapping data."""
    try:
        stat=Path(path).stat()
        points=_centers(str(path),stat.st_mtime_ns,stat.st_size,int(page_number),int(expected_count),str(expected_hash))
    except (OSError,ValueError,RuntimeError,ImportError):return None
    if not points:return None
    rows=[]
    for x,y in sorted(points,key=lambda p:(p[1],p[0])):
        if not rows or abs(y-rows[-1][0][1])>1.0:rows.append([])
        rows[-1].append((x,y))
    slots={(r,c):(x,y) for r,row in enumerate(rows,1) for c,(x,y) in enumerate(sorted(row),1)}
    known={}
    for tube in tubes:
        key=(tube.get('row'),tube.get('column'))
        if key not in slots or key in known:return None
        known[key]=tube
    output=[]
    for (row,column),(x,y) in slots.items():
        item=dict(known[(row,column)]) if (row,column) in known else {
            'tube_id':None,'tube_no':f'PDF-{row}-{column}','lifecycle_no':None,
            'current_status':'UNKNOWN','operational_status':'UNKNOWN',
            'operational_status_source':'UNREGISTERED_DISPLAY_POSITION',
            'inspection_status':'UNKNOWN','category':'UNREGISTERED','inspected':False,
            'wall_loss_percent':None,'minimum_wall_thickness_mm':None,'indications':[],
            'indication_count':0,'measured_indication_count':0,'scopes':[],
            'managed':False,'coordinate_is_verified':False,'position_locked':True}
        item.update(row=row,column=column,x=x,y=y,z=0,source_x=x,source_y=y,
            position_source='PDF_VECTOR_DISPLAY',coordinate_source='PDF_VECTOR_DISPLAY',
            display_slot=len(output)+1)
        output.append(item)
    return output
