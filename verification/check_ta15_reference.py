"""Read-only TA15 audit against compiled official Fortran + GEOPACK08."""
import argparse
from datetime import datetime,timedelta
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import warnings
import numpy as np


def reference(executable,queries):
    lines=[]
    for mode,values in queries:
        lines.extend([str(mode),' '.join(str(x) for x in values)])
    p=subprocess.run([str(executable)],input='\n'.join(lines)+'\n',capture_output=True,text=True,timeout=120)
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    results=[np.array([float(x) for x in line.split()[1:]]) for line in p.stdout.splitlines() if line.startswith('RESULT ')]
    if len(results)!=len(queries):raise ValueError('Reference output count mismatch: '+p.stdout[-2000:])
    return results


def frame(exe,date,velocity):
    row=reference(exe,[(1,[date.year,date.timetuple().tm_yday,date.hour,date.minute,date.second,*velocity])])[0]
    tilt=float(row[0]);rotation=row[1:].reshape(3,3)
    # Legacy GEOPACK constants yield ~1e-11 orthogonality residuals.
    # Record them in the report; 1e-9 is a numerical sanity bound, not a field-error allowance.
    np.testing.assert_allclose(rotation@rotation.T,np.eye(3),atol=1e-9,rtol=0)
    if abs(np.linalg.det(rotation)-1)>1e-9:raise ValueError('Invalid handedness.')
    return tilt,rotation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    args=parser.parse_args();exe=args.reference.resolve()
    root=Path(__file__).resolve().parent/'ta15-audit'
    from gtsimulation.magnetic_field.magnetosphere.Functions.t15B import t15B
    import inspect
    from gtsimulation.magnetic_field.magnetosphere import Tsyganenko
    from gtsimulation.input_data.ta15 import DTYPE
    import gtsimulation.magnetic_field.magnetosphere._tsyganenko as wrapper
    points=[[6,1,2],[-6,0,1],[-10,5,2],[-20,-5,.5],[3,3,3],[-40,10,4]]
    cases=list(itertools.product([[2,0,0,0],[2,3,-5,1],[5,-6,-10,2]],[-.4,0,.4],points))
    official=reference(exe,[(0,[*p,ps,*x]) for p,ps,x in cases])
    kernel=[]
    for (p,ps,x),expected in zip(cases,official):
        actual=np.array(t15B(np.array(p,dtype=float),ps,*x))
        kernel.append({'parameters':p,'tilt_rad':ps,'position_RE':x,'official_nT':expected.tolist(),'gt_kernel_nT':actual.tolist(),
                       'max_abs_error_nT':float(np.max(abs(actual-expected))),
                       'within_1e-6nT_plus_1e-6relative':bool(np.allclose(actual,expected,atol=1e-6,rtol=1e-6))})
    raw=np.loadtxt(root.parent/'live/ta15-zm2iaaf6/2023_OMNI_5m_with_TA15_drivers.dat')
    chosen=[]
    for target in [datetime(2023,1,1),datetime(2023,3,21),datetime(2023,6,21),datetime(2023,9,23),datetime(2023,12,21)]:
        day=target.timetuple().tm_yday
        ok=raw[(raw[:,1]==day)&(raw[:,13]==1)&(raw[:,14]==1)&(raw[:,18]>=0)&(raw[:,18]<=2)]
        if not len(ok):raise ValueError('No observed valid row on '+str(target))
        chosen.append(ok[len(ok)//2])
    coordinate=[];wrapper_comparison=[]
    for r in chosen:
        date=datetime(int(r[0]),1,1)+timedelta(days=int(r[1])-1,hours=int(r[2]),minutes=int(r[3]))
        par=r[[16,5,6,18]]
        gps,gsm=frame(exe,date,[-400,0,0])
        # Control: truly radial flow makes GSW exactly GSM in official GEOPACK.
        controlps,control=frame(exe,date,[-800,0,0])
        np.testing.assert_allclose(gsm,control,atol=1e-12,rtol=0)
        np.testing.assert_allclose(gps,controlps,atol=1e-12,rtol=0)
        rows=np.zeros(1,dtype=DTYPE);rows['date']=np.datetime64(date)
        rows['T15B_input']=par;rows['imf_flag']=rows['sw_flag']=1
        saved=root/'sample-inputs.npy';np.save(saved,rows,allow_pickle=False)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            gt=Tsyganenko(date,'15B',input_file=saved)
        for vy_correction in [0.,29.77]:
            vel=r[7:10].copy();vel[1]+=vy_correction
            ps,gsw=frame(exe,date,vel)
            for point in points:
                geo=gsm.T@np.array(point)
                gsw_position=gsw@geo
                # Same model kernel and same drivers; only frames/tilt differ.
                base,correct=reference(exe,[(0,[*par,gps,*point]),(0,[*par,ps,*gsw_position])])
                base_geo=gsm.T@base;correct_geo=gsw.T@correct
                delta=float(np.linalg.norm(base_geo-correct_geo))
                coordinate.append({'date_UTC':date.isoformat()+'Z','GSM_position_RE':point,
                    'velocity_GSE_km_s':vel.tolist(),'added_to_source_Vy_km_s':vy_correction,
                    'source_GSW_tilt_rad':float(r[15]),'reference_GSW_tilt_rad':ps,'reference_GSM_tilt_rad':gps,
                    'GSW_rotation_orthogonality_error':float(np.max(abs(gsw@gsw.T-np.eye(3)))),
                    'GSM_rotation_orthogonality_error':float(np.max(abs(gsm@gsm.T-np.eye(3)))),
                    'source_minus_reference_tilt_rad':float(r[15]-ps),
                    'angle_between_X_axes_deg':float(np.degrees(np.arccos(np.clip(gsm[0]@gsw[0],-1,1)))),
                    'mixed_frame_field_GEO_nT':base_geo.tolist(),'consistent_GSW_field_GEO_nT':correct_geo.tolist(),
                    'difference_norm_nT':delta,'difference_relative_to_consistent_norm':delta/max(float(np.linalg.norm(correct_geo)),1e-15)})
                if vy_correction==0:
                    actual=np.array(gt.calc_field(*geo))
                    # Re-run official kernel using exactly the GT-selected float32 drivers,
                    # GT tilt and GT positions to isolate port errors from wrapper geometry.
                    from gtsimulation.magnetic_field.magnetosphere.Functions import transformations as tr
                    xgt=tr.geo2gsm(*geo,gt.year,gt.doy,gt.sec,gt.g,gt.h)
                    rawref=reference(exe,[(0,[*gt.parmod,float(gt.ps),*xgt])])[0]
                    refgeo=np.array(tr.geo2gsm(*rawref,gt.year,gt.doy,gt.sec,gt.g,gt.h,inverse=True))
                    wrapper_comparison.append({'date_UTC':date.isoformat()+'Z','GEO_position_RE':geo.tolist(),
                        'gt_wrapper_nT':actual.tolist(),'official_kernel_with_GT_geometry_nT':refgeo.tolist(),
                        'port_only_difference_norm_nT':float(np.linalg.norm(actual-refgeo)),
                        'gt_wrapper_minus_official_GSM_geometry_norm_nT':float(np.linalg.norm(actual-base_geo)),
                        'GT_GSM_tilt_rad':float(gt.ps),'GEOPACK_GSM_tilt_rad':gps})
    source_files=['TA_2015_B.f','geopack08.for','TA15_Model_description.pdf','reference_driver.f90']
    result={'audit_complete':True,'runtime_model_modified':False,
        'official_sources':{'TA15':'https://geo.phys.spbu.ru/~tsyganenko/models/ta15/TA_2015_B.f',
            'GEOPACK':'https://geo.phys.spbu.ru/~tsyganenko/Geopack-2008_dp.for'},
        'sha256':{n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in source_files},
        'reference_executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
        'gt_wrapper_module':wrapper.__file__,
        'gt_wrapper_sha256':hashlib.sha256(Path(wrapper.__file__).read_bytes()).hexdigest(),
        'gt_kernel_sha256':hashlib.sha256(Path(inspect.getfile(t15B.py_func if hasattr(t15B,'py_func') else t15B)).read_bytes()).hexdigest(),
        'source_drivers_sha256':hashlib.sha256((root.parent/'live/ta15-zm2iaaf6/2023_OMNI_5m_with_TA15_drivers.dat').read_bytes()).hexdigest(),
        'kernel_comparisons':kernel,'frame_sensitivity':coordinate,
        'wrapper_comparisons':wrapper_comparison,
        'summary':{'kernel_cases':len(kernel),'kernel_cases_within_tolerance':sum(c['within_1e-6nT_plus_1e-6relative'] for c in kernel),
            'kernel_max_abs_error_nT':max(c['max_abs_error_nT'] for c in kernel),
            'frame_cases':len(coordinate),'max_frame_difference_nT':max(c['difference_norm_nT'] for c in coordinate),
            'max_port_only_difference_nT':max(c['port_only_difference_norm_nT'] for c in wrapper_comparison)},
        'limitations':['Finite selected cases, not a global error bound.',
            'The two Vy conventions bracket an unresolved provenance choice for the supplied annual driver velocities; neither is silently certified as truth.',
            'GSW frame sensitivity is compared using the same official kernel/IGRF14 frames. Published source tilt may use different ephemeris/IGRF versions and is recorded separately.',
            'Differences are not validation against spacecraft observations.']}
    path=root/'audit_result.json';path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2));print('Evidence: '+str(path))


if __name__=='__main__':main()
