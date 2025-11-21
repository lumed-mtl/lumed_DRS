try:
    import oras.backend.external_trigger as ext
except ModuleNotFoundError:
    print("ORAS package not found")


print(ext.get_profiles())