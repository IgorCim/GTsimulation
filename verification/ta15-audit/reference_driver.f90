program reference_driver
  implicit none
  integer :: mode,ios,iy,id,ih,im,is,j,k
  real(8) :: p(10),ps,x,y,z,bx,by,bz,vx,vy,vz,geo(3),gsw(3),rot(3,3)
  real(8) :: common_values(34)
  common /GEOPACK1/ common_values
  do
    read(*,*,iostat=ios) mode
    if(ios/=0) exit
    if(mode==0) then
      p=0d0
      read(*,*) p(1:4),ps,x,y,z
      call TA_2015_B(0,p,ps,x,y,z,bx,by,bz)
      write(*,'(A,3ES26.17)') 'RESULT ',bx,by,bz
    else if(mode==1) then
      read(*,*) iy,id,ih,im,is,vx,vy,vz
      call RECALC_08(iy,id,ih,im,is,vx,vy,vz)
      do j=1,3
        geo=0d0
        geo(j)=1d0
        call GEOGSW_08(geo(1),geo(2),geo(3),gsw(1),gsw(2),gsw(3),1)
        rot(:,j)=gsw
      enddo
      write(*,'(A,10ES26.17)') 'RESULT ',common_values(16),((rot(j,k),k=1,3),j=1,3)
    else
      stop 2
    endif
  enddo
end program
