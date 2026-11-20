"""Saved inputs -> four short GT runs -> independently reopened HDF5 files."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import warnings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundles',type=Path)
    parser.add_argument('--require-clean',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    if args.bundles is None:
        candidates=[p for p in root.glob('reuse-*/report.json') if json.loads(p.read_text())['status']=='PASS']
        if not candidates:parser.error('Run check_reuse.py first.')
        args.bundles=max(candidates,key=lambda p:p.stat().st_mtime).parent/'bundles.json'
    bundles=json.loads(args.bundles.read_text())
    folder=Path(tempfile.mkdtemp(prefix='workflow-',dir=root))
    result={'status':'RUNNING','scenarios':{},'python':sys.executable,'prefix':sys.prefix,
            'scope':'Engineering input-to-HDF5 smoke, 10 steps, 1 proton per scenario; not convergence or physical model validation.'}
    try:
        print("Loading installed GT and dependencies (first JIT import may take minutes)...",flush=True)
        import h5py
        import numpy as np
        import gtsimulation
        from importlib.metadata import version
        from gtsimulation.common import Units
        from gtsimulation.magnetic_field import Uniform
        from gtsimulation.magnetic_field.magnetosphere import Tsyganenko
        from gtsimulation.medium.magnetosphere import GTnrlmsis
        from gtsimulation.particle import Flux,generator
        from gtsimulation.pusher import BunemanBorisSimulator
        import site
        prefix=Path(sys.prefix).resolve()
        modules={}
        for name in ('numpy','h5py','numba','scipy','pyproj','particle','pymsis','gtsimulation'):
            mod=__import__(name)
            path=Path(mod.__file__).resolve();modules[name]={'version':version(name),'file':str(path)}
            if args.require_clean and not path.is_relative_to(prefix):
                raise ValueError('Module outside clean environment: '+name)
        if args.require_clean:
            if site.ENABLE_USER_SITE:raise ValueError('User site packages enabled.')
            config=(prefix/'pyvenv.cfg').read_text().lower()
            if 'include-system-site-packages = false' not in config:raise ValueError('System packages inherited.')
        result.update(modules=modules,require_clean=args.require_clean)
        for model in ('89','96','15B','nrlmsis'):
            print('Simulating and reopening HDF5: '+model,flush=True)
            bundle=bundles[model];input_path=Path(bundle['input_file'])
            manifest_path=Path(bundle['manifest'])
            m=json.loads(manifest_path.read_text())
            actual_hash=hashlib.sha256(input_path.read_bytes()).hexdigest()
            if actual_hash!=m['input_sha256']:raise ValueError('Input hash mismatch.')
            date=datetime.fromisoformat(m['start'].replace('Z','+00:00')).replace(tzinfo=None)
            medium=None
            if model=='nrlmsis':
                field=Uniform(B=np.array([0,0,10.]))
                medium=GTnrlmsis(date,input_file=input_path)
                initial=[6478137.,0,0]
            else:
                with warnings.catch_warnings(record=True) as notes:
                    warnings.simplefilter('always')
                    field=Tsyganenko(date,model,input_file=input_path)
                if model=='15B' and not any('GSW' in str(n.message) for n in notes):raise ValueError('Missing T15B warning.')
                initial=[2*Units.RE,0,0]
            particles=Flux(Spectrum=generator.spectrum.Monolines(energy=Units.GeV),
                Distribution=generator.distribution.UserInput(R0=initial,V0=[0,1,0]),Names='proton',Nevents=1)
            output=folder/(model+'.h5')
            sim=BunemanBorisSimulator(Particles=particles,Num=10,Step=1e-6,
                Bfield=field,Medium=medium,Date=date,Output=str(output),Verbose=0,Save=1,
                UseDecay=False,InteractNUC=None,RadLosses=False)
            sim()
            del sim
            with h5py.File(output,'r') as f:
                if not bool(f.attrs['complete']):raise ValueError('Incomplete HDF5.')
                if list(f['events'])!=['0']:raise ValueError('Unexpected event count.')
                coords=f['events/0/Track/Coordinates'][:]
                velocity=f['events/0/Track/Velocities'][:]
                if coords.shape!=(10,3) or velocity.shape!=(10,3):raise ValueError('Unexpected track shape.')
                if not np.all(np.isfinite(coords)) or not np.all(np.isfinite(velocity)):raise ValueError('Nonfinite track.')
                np.testing.assert_allclose(np.linalg.norm(velocity,axis=1),1,rtol=0,atol=1e-10)
                np.testing.assert_allclose(f['events/0/Particle/R0'][:],initial,rtol=0,atol=1e-6)
                if int(f['events/0/Particle/PDG'][()])!=2212:raise ValueError('Wrong particle.')
                np.testing.assert_allclose(f['events/0/Particle/T0'][()],Units.GeV,rtol=1e-12)
                displacement=float(np.linalg.norm(coords[-1]-coords[0]))
                if displacement<=0:raise ValueError('No track motion.')
            result['scenarios'][model]={'status':'PASS','input_file':str(input_path),
                'input_sha256':actual_hash,'manifest_file':str(manifest_path),
                'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                'hdf5':str(output),'hdf5_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                'steps_saved':10,'particle':'proton','kinetic_energy_MeV':float(Units.GeV),
                'step_seconds':1e-6,'coordinates_unit':'m','stored_velocity_unit':'dimensionless','stored_velocity_meaning':'normalized direction Vm/V_norm',
                'first_to_last_displacement_m':displacement,'read_back_complete':True}
        result['status']='PASS'
    except BaseException as exc:
        result.update(status='FAIL',error_type=type(exc).__name__,error=str(exc));raise
    finally:
        report=folder/'report.json';report.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print('Evidence: '+str(report),flush=True)
    print('PASS: four saved-input -> simulation -> HDF5 read-back workflows.',flush=True)


if __name__=='__main__':main()
