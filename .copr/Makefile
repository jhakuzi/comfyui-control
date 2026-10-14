# COPR's "make srpm" SCM build method. Run from the repository root.
srpm:
	dnf -y install python3 rpm-build
	python3 packaging/make_srpm.py --outdir "$(outdir)"
