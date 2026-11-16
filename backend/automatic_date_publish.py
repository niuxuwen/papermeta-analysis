"""Bounded date-publication retries, independent of a long review cycle."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import time

from automatic_date_service import locked,publish,atomic,now


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--force',action='store_true');a=parser.parse_args()
    with locked(a.state/'date-publisher.lock')as acquired:
        if not acquired:return
        if not(a.state/'registry.json').exists():return
        previous=a.state/'last-published.json'
        if previous.exists()and not a.force:
            stamp=json.loads(previous.read_text()).get('published_at')
            if stamp and (datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()<300:return
        for attempt in range(5):
            try:result=publish(a.project,a.state)
            except Exception as e:
                result={'status':'PUBLICATION_FAILED','error':type(e).__name__+':'+str(e)[:400]}
            atomic(a.state/'date-publisher-status.json',{'at':now(),'attempt':attempt+1,**result})
            if result['status']!='PUBLISHER_BUSY':print(json.dumps(result),flush=True);return
            if attempt<4:time.sleep(10)
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
