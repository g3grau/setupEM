"""Parse and compact GDS datatype filters; colon endpoints are inclusive."""
import ast
import re


def parse_datatypes(value):
    if isinstance(value,str):
        text=value.strip()
        if text.lower() in ('*','all'):return list(range(65536))
        if not text:return []
        if ':' in text:
            result=[]
            for token in text.split(','):
                match=re.fullmatch(r'\s*(\d+)\s*(?::\s*(\d+)\s*)?',token)
                if not match:raise ValueError('Use datatypes or inclusive ranges, e.g. 0:30,40,50,60')
                lo=int(match[1]);hi=int(match[2]) if match[2] else lo
                if not 0<=lo<=hi<=65535:raise ValueError('Ranges must increase within 0..65535')
                result.extend(range(lo,hi+1))
            return list(dict.fromkeys(result))
        try:value=ast.literal_eval('['+text+']')
        except (ValueError,SyntaxError) as error:raise ValueError('Invalid datatype filter') from error
    result=[];pending=[value]
    while pending:
        item=pending.pop(0)
        if isinstance(item,(list,tuple)):pending[0:0]=list(item)
        elif isinstance(item,bool):raise ValueError('Datatypes must be integers')
        elif isinstance(item,int) or isinstance(item,float) and item.is_integer():
            item=int(item)
            if not 0<=item<=65535:raise ValueError('Datatypes must be within 0..65535')
            result.append(item)
        else:raise ValueError('Datatypes must be integers')
    return list(dict.fromkeys(result))


def format_datatypes(value):
    values=sorted(set(parse_datatypes(value)))
    if len(values)==65536:return '*'
    if not values:return ''
    runs=[];lo=hi=values[0]
    for n in values[1:]:
        if n==hi+1:hi=n
        else:
            runs.append(str(lo) if lo==hi else f'{lo}:{hi}');lo=hi=n
    runs.append(str(lo) if lo==hi else f'{lo}:{hi}')
    return ', '.join(runs)
