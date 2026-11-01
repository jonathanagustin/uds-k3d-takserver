	public void init(ServiceContext ctx) throws Exception {
    	if (getRemoteConfiguration().getCluster().isEnabled() && getRemoteConfiguration().getCluster().isCacheConfig()) {
    		loadConfigFromCache();
    	}
    	
    	IgniteReconnectEventHandler.registerListener(() -> {
    		continuousConfigurationQuery.setLocalListener((evts) -> {
       	     for (CacheEntryEvent<? extends String, ? extends Configuration> e : evts) {
       	    	 this.setConfiguration(e.getValue());
       	    	 saveChanges();
       	     }
         	 });
    		
    		getConfigurationCache().query(continuousConfigurationQuery);	
    	});
    	
		if (logger.isDebugEnabled()) {
			logger.debug("init method " + getClass().getSimpleName());
		}
	}
