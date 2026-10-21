"""Audit supplied VEX AIM reference against the catalogue; emit a reviewable matrix.

Usage: python dev/capability_matrix.py REFERENCE.html
The reference stays outside the repository. Only API names/dispositions are saved.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

class Text(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]
    def handle_data(self, text): self.parts.append(text)

def matrix(reference):
    parser=Text(); parser.feed(Path(reference).read_text(encoding='utf-8'))
    text=' '.join(parser.parts)
    native={}
    for row in (ROOT/'cli/vexaim/src/catalog.tsv').read_text().splitlines():
        if row.startswith('#') or not row.strip(): continue
        command,method,kind,_=row.split('|')
        native.setdefault(method,[]).append(command)
    names=sorted(set(re.findall(r'(?:robot|onestick)\.[a-zA-Z_][\w.]*',text)))
    extras={
        'robot.get_battery_capacity':('unsupported','Remote-library alias; on-robot canonical getter is get_battery_level'),
        'robot.has_any_barrel':('command','cargo has-any-barrel maps robot.vision.has_any_barrel'),
        'robot.has_blue_barrel':('command','cargo has-blue-barrel maps robot.vision.has_blue_barrel'),
        'robot.has_orange_barrel':('command','cargo has-orange-barrel maps robot.vision.has_orange_barrel'),
        'robot.has_sports_ball':('command','cargo has-sports-ball maps robot.vision.has_sports_ball'),
        'robot.link':('prerequisite','Two AIMs manually linked in Settings; missing on older firmware'),
        'robot.link.get_name':('unsupported','Remote extension not established in on-robot SDK'),
        'robot.robot_send':('unsupported','Remote WebSocket transport internals; outside USB/BLE scope'),
        'robot.sound.play_local_file':('host-only','assets sound upload is encoding-gated; sound play-file handles playback'),
        'robot.status':('host-only','info/capabilities live status; no remote WebSocket cache'),
        'robot.stop_program':('unsupported','Saved program control excluded; stop bounds transient helpers'),
        'robot.vision.get_camera_image':('host-only','camera observe; native camera bytes plus artifact metadata'),
    }
    rows=[]
    for name in names:
        if name in native: disposition='command'; detail=', '.join(native[name])
        elif name.endswith(('.pressed','.released','.crashed','.connected','.disconnected','.handle_message')):
            disposition='event'; detail='events watch '+name.removeprefix('robot.').removeprefix('onestick.')
        elif name in extras: disposition,detail=extras[name]
        else: raise AssertionError('Unmapped reference API: '+name)
        rows.append(dict(api=name,disposition=disposition,detail=detail))
    return dict(schema_version=1,model='VEX AIM',source='VEX_AIM_Software_Capability_Reference.html (user supplied)',
                note='Command presence is implementation coverage, not hardware verification; consult hardware-notes.md',
                api=rows,python_features=['conditions','loops','variables','functions','Thread','Timer.event','math','random','time','json','sys','gc','micropython','array','struct','collections','io','errno','os','re'],
                blocks='Block control/math/logic constructs use standard Python via exec; runtime device blocks map to catalogue groups',
                host_operations=['pairing','sessions','camera observe','snap','asset slots'],
                exclusions=['firmware updates','saved programs','other VEX models','Wi-Fi','raw encoders','microphone capture','custom neural training'])

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(matrix(sys.argv[1]),indent=2,ensure_ascii=False))
