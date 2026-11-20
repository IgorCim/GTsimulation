"""Network-dependent smoke check; run from the repository after installation."""
from pathlib import Path
from datetime import datetime
import json
import hashlib
import warnings
import numpy as np
from gtsimulation.input_data import download_ta15_inputs, download_atmosphere_inputs
from gtsimulation.input_data.ta15 import COMPATIBILITY
from gtsimulation.magnetic_field.magnetosphere import Tsyganenko
from gtsimulation.medium.magnetosphere import GTnrlmsis

root=Path(__file__).resolve().parent
atmos=download_atmosphere_inputs('2024-09-10','2024-09-11',root/'live')
medium=GTnrlmsis(datetime(2024,9,10),input_file=atmos['input_file'])
medium.calculate_model(6478137,0,0)
assert np.isfinite(medium.get_density()) and medium.get_density()>0
atmos['density_at_equator_100km_kg_m3']=float(medium.get_density())
ta15=download_ta15_inputs('2023-01-01T00:30','2023-01-01T01:30',root/'live',allow_interpolated=True)
with warnings.catch_warnings(record=True) as notices:
 warnings.simplefilter('always')
 field=Tsyganenko(datetime(2023,1,1,0,30),'15B',input_file=ta15['input_file'])
assert any(COMPATIBILITY==str(w.message) for w in notices)
values=field.calc_field(2,1,1)
assert np.all(np.isfinite(values))
ta15['field_at_2_1_1_RE_nT']=[float(x) for x in values]
# Verify the full downloaded year against the original GT snapshot, at snapshot precision.
source=Path(ta15['input_file']).parent/'2023_OMNI_5m_with_TA15_drivers.dat'
raw=np.loadtxt(source)
import gtsimulation.magnetic_field.magnetosphere._tsyganenko as module
old=np.load(Path(module.__file__).parent/'Data'/'T_input15B_short.npy')
old=old[(old['date']>=np.datetime64('2023-01-01'))&(old['date']<np.datetime64('2024-01-01'))]
assert len(old)==len(raw)
np.testing.assert_array_equal(old['T15B_input'],raw[:,[16,5,6,18]].astype(old['T15B_input'].dtype))
from datetime import timedelta
dates=np.array([datetime(int(y),1,1)+timedelta(days=int(d)-1,hours=int(h),minutes=int(m)) for y,d,h,m in raw[:,:4]],dtype='datetime64[s]')
np.testing.assert_array_equal(old['date'],dates)
ta15['snapshot_rows_compared']=len(old)
result={'atmosphere':atmos,'ta15':ta15,'scope':'Input-to-model smoke; not scientific validation of the field or medium.'}
(root/'expanded_live_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
